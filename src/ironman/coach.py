"""AI coach: LLM proposes a weekly plan as JSON, deterministic guardrails make it safe to show."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, timedelta
from typing import Literal

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError

from ironman import analysis, metrics
from ironman.config import get_settings

INTENSITY_IF = {"rest": 0.0, "easy": 0.65, "moderate": 0.80, "hard": 0.95}
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
MAX_ATTEMPTS = 3


class Session(BaseModel):
    day: Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    sport: Literal["swim", "bike", "run", "rest"]
    minutes: int = Field(ge=0, le=480)
    intensity: Literal["rest", "easy", "moderate", "hard"]
    intent: str = Field(max_length=300)


class Plan(BaseModel):
    sessions: list[Session]


class LLMError(Exception):
    pass


def session_load(s: Session) -> float:
    return s.minutes / 60 * INTENSITY_IF[s.intensity] ** 2 * 100


def plan_load(plan: Plan) -> float:
    return sum(session_load(s) for s in plan.sessions)


def build_inputs(conn, week_start: date) -> dict:
    """Aggregates only. No identity, no coordinates, no tokens."""
    weeks = metrics.weekly_volume(conn)
    by_week: dict[date, dict] = {}
    for w in weeks:
        d = by_week.setdefault(w["week_start"], {"tss": 0.0, "hours": {}})
        d["tss"] += w["tss"]
        d["hours"][w["sport"]] = round(w["hours"], 1)
    recent = sorted(by_week.items())[-8:]
    m = conn.execute(
        "SELECT ctl, atl, tsb FROM private.daily_metrics ORDER BY day DESC LIMIT 1"
    ).fetchone()
    prev_tss = by_week.get(week_start - timedelta(days=7), {}).get("tss")
    if not prev_tss and m:
        prev_tss = m["ctl"] * 7  # steady-state weekly load implied by fitness
    goal = metrics.goal_progress(conn)
    return {
        "week_start": week_start.isoformat(),
        "previous_week_tss": round(prev_tss or 0),
        "recent_weeks": [
            {"week_start": k.isoformat(), "tss": round(v["tss"]), "hours": v["hours"]}
            for k, v in recent
        ],
        "fitness": {k: round(m[k], 1) for k in ("ctl", "atl", "tsb")} if m else None,
        "weeks_to_race": goal["weeks_remaining"] if goal else None,
        "overtraining_risk": analysis.overtraining_risk(conn),
        "race_time_estimate": analysis.predict_race_time(conn),
    }


def build_prompt(inputs: dict) -> str:
    cap = int(get_settings().max_weekly_load_increase * 100)
    return (
        "You are an endurance coach for a triathlete training for a full Ironman. Using ONLY the data "
        f"below, propose next week's plan. Weekly load must not exceed previous_week_tss by more than {cap}%. "
        "Include at least one rest day. Reply with JSON only, shaped as "
        '{"sessions":[{"day":"mon|tue|wed|thu|fri|sat|sun","sport":"swim|bike|run|rest",'
        '"minutes":int,"intensity":"rest|easy|moderate|hard","intent":"short text"}]}.\n\n'
        f"DATA:\n{json.dumps(inputs)}"
    )


def anthropic_llm(prompt: str) -> str:
    s = get_settings()
    if not s.llm_api_key:
        raise LLMError("IRONMAN_LLM_API_KEY is not configured")
    try:
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            timeout=60,
            headers={"x-api-key": s.llm_api_key, "anthropic-version": "2023-06-01"},
            json={
                "model": s.llm_model,
                "max_tokens": 1500,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        r.raise_for_status()
        return r.json()["content"][0]["text"]
    except httpx.HTTPError as e:
        raise LLMError(f"LLM API unavailable: {e}") from e


def parse_plan(text: str) -> Plan:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in LLM output")
    return Plan.model_validate(json.loads(text[start : end + 1]))


def apply_guardrails(plan: Plan, previous_tss: float, risk_level: str) -> tuple[Plan, list[dict]]:
    """Return a safe plan and a record of every adjustment made."""
    adj: list[dict] = []
    sessions = [s.model_copy() for s in plan.sessions]
    if not any(s.intensity == "rest" or s.sport == "rest" for s in sessions):
        lightest = min(sessions, key=session_load)
        adj.append(
            {"rule": "rest_day", "detail": f"converted {lightest.day} {lightest.sport} to rest"}
        )
        lightest.sport, lightest.intensity, lightest.minutes = "rest", "rest", 0
        lightest.intent = "rest day (added by safety rule)"
    cap = get_settings().max_weekly_load_increase
    limit = previous_tss * (1 + cap)
    rule = "load_cap"
    if risk_level == "high":
        limit, rule = previous_tss * 0.8, "risk_reduction"
    if previous_tss > 0:
        load = sum(session_load(s) for s in sessions)
        if load > limit:
            f = limit / load
            for s in sessions:
                s.minutes = int(s.minutes * f)
            adj.append(
                {
                    "rule": rule,
                    "detail": f"scaled sessions by {f:.2f}: {load:.0f} -> {limit:.0f} TSS "
                    f"(previous week {previous_tss:.0f})",
                }
            )
    return Plan(sessions=sorted(sessions, key=lambda s: DAYS.index(s.day))), adj


def generate_plan(
    conn, week_start: date, llm: Callable[[str], str] | None = None, redis=None
) -> dict:
    s = get_settings()
    llm = llm or anthropic_llm
    if redis is not None:
        key = f"llm:calls:{date.today()}"
        n = redis.incr(key)
        redis.expire(key, 2 * 86400)
        if n > s.llm_max_calls_per_day:
            raise HTTPException(429, "daily plan generation limit reached")
    inputs = build_inputs(conn, week_start)
    prompt = build_prompt(inputs)
    last_err = ""
    for _ in range(MAX_ATTEMPTS):
        try:
            plan = parse_plan(llm(prompt))
            break
        except LLMError as e:
            raise HTTPException(503, str(e)) from e
        except (ValueError, ValidationError) as e:
            last_err = str(e)
    else:
        raise HTTPException(
            502, f"LLM returned an invalid plan after {MAX_ATTEMPTS} attempts: {last_err[:200]}"
        )
    safe, adjustments = apply_guardrails(
        plan, inputs["previous_week_tss"], inputs["overtraining_risk"]["level"]
    )
    result = {
        "sessions": [x.model_dump() for x in safe.sessions],
        "planned_tss": round(plan_load(safe)),
    }
    row = conn.execute(
        "INSERT INTO private.plans (week_start, plan, inputs, adjustments) VALUES (%s,%s,%s,%s) RETURNING id, created_at",
        (week_start, json.dumps(result), json.dumps(inputs), json.dumps(adjustments)),
    ).fetchone()
    return {
        "id": str(row["id"]),
        "week_start": week_start,
        "plan": result,
        "adjustments": adjustments,
        "disclaimer": "Training signals only, not medical advice.",
    }
