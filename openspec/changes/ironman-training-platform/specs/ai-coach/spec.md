## Purpose

Generate safe, personalised weekly training plans with an external LLM, grounded in the owner's metrics and ML predictions and bounded by deterministic guardrails.

## ADDED Requirements

### Requirement: Weekly plan generation
The system SHALL generate a weekly plan covering swim, bike, run and rest days on request and on a weekly schedule, using the owner's recent metrics, race goal and ML predictions as input.

#### Scenario: Owner requests a plan
- **WHEN** the owner requests next week's plan
- **THEN** the system returns a structured plan with a session per day (sport, duration, intensity, intent)

#### Scenario: Plan grounded in data
- **WHEN** a plan is generated
- **THEN** the data inputs supplied to the LLM (metrics window, predictions) are stored with the plan

### Requirement: Load guardrails
The system SHALL validate every generated plan against deterministic limits and SHALL NOT present a plan that violates them.

#### Scenario: Excessive load increase
- **WHEN** a plan raises weekly load more than the configured cap (default 10%) over the previous week
- **THEN** the plan is rejected or reduced to the cap and the adjustment is recorded

#### Scenario: Elevated overtraining risk
- **WHEN** the overtraining-risk signal is high
- **THEN** the plan includes reduced load or recovery and the reason is shown

#### Scenario: Malformed LLM output
- **WHEN** the LLM response does not match the plan schema
- **THEN** the system retries a bounded number of times and otherwise reports failure without storing a partial plan

### Requirement: Safe degradation
The system SHALL keep all non-AI features working when the LLM API is unavailable and SHALL bound LLM usage and cost.

#### Scenario: LLM outage
- **WHEN** the LLM API is unreachable
- **THEN** plan generation reports a clear error and the rest of the application is unaffected

#### Scenario: Rate limit
- **WHEN** plan requests exceed the configured limit
- **THEN** further requests are refused until the window resets

### Requirement: Privacy of prompts
The system SHALL NOT send owner identity, precise GPS coordinates or credentials to the LLM API.

#### Scenario: Prompt contents
- **WHEN** a prompt is built
- **THEN** it contains only aggregated training data and no name, email, location coordinates or tokens

### Requirement: Disclaimer
The system SHALL display that plans and predictions are training signals and not medical advice wherever they are shown.

#### Scenario: Plan view
- **WHEN** a plan or prediction is displayed
- **THEN** the disclaimer is visible on the same view
