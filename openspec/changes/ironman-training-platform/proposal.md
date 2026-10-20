## Why

Training for an Ironman produces a large volume of workout data that is spread across Garmin and Strava and rarely turned into decisions. This change builds a single platform that ingests that data, computes load and fitness metrics, forecasts race readiness with ML, and produces guarded weekly training plans. It also serves as a production-grade portfolio piece demonstrating Terraform, Kubernetes, PostgreSQL and Redis, with an anonymized public dashboard that can be shared safely.

## What Changes

- Add workout ingestion from Strava (webhooks and API sync) and from uploaded FIT/GPX files. Garmin Connect data is brought in via FIT files and, if partner API access is granted, API sync.
- Add an endurance metrics engine: training stress, CTL/ATL/TSB, per-sport volume, pace/power/HR zones and race-goal progress.
- Add an AI coach that asks an external LLM API for weekly plans grounded in the athlete's metrics and ML predictions, with enforced guardrails (capped weekly load increase, minimum recovery).
- Add an ML pipeline: race-time prediction, fitness forecast, overtraining risk and anomaly detection (HR drift). Models are pretrained on open datasets, fine-tuned on the owner's data, tracked in MLflow and served by a FastAPI inference service.
- Add a role-based access model: owner (OAuth + 2FA), invited viewers (revocable signed share links, read-only) and public (anonymized only), plus a synthetic-data demo mode.
- Add server-side anonymization: a scheduled job writes sanitized data into separate public tables; the public API reads only those tables.
- Add a public dashboard (no login) with trends, percentiles and progress, and a private owner dashboard.
- Add infrastructure and delivery: Terraform (VM, storage, DNS, remote state), k3s cluster, Helm charts, ArgoCD GitOps, GitHub Actions CI, External Secrets, cert-manager TLS, Prometheus/Grafana/Loki monitoring.
- Add README documentation of privacy-by-design and architecture with diagrams and a live demo link, and a disclaimer that ML/AI output is a training signal, not medical advice.

## Capabilities

### New Capabilities
- `workout-ingestion`: Strava webhook/API sync and FIT/GPX import, de-duplication, Redis-queued jobs, storage in PostgreSQL/TimescaleDB.
- `training-metrics`: Training stress, CTL/ATL/TSB, per-sport volume, zones and race-goal progress computed from stored workouts.
- `ai-coach`: LLM-generated weekly plans grounded in metrics and predictions, with deterministic guardrails and plan validation.
- `ml-analysis`: Feature engineering, model training, registry and inference for race-time prediction, fitness forecast, overtraining risk and anomaly detection, with open-dataset pretraining.
- `access-control`: Owner login (OAuth + 2FA), signed revocable viewer share links, public role, demo mode.
- `public-anonymization`: Identity separation, pseudonymous IDs, GPS/time/field coarsening, percentile-based stats and the scheduled sanitization job feeding public-only tables.
- `public-dashboard`: Unauthenticated anonymized dashboard and the read-only public API that backs it.
- `platform-infrastructure`: Terraform, k3s, Helm, ArgoCD, CI, secrets management, ingress/TLS, observability and local dev environment.

### Modified Capabilities
<!-- None: the repository has no existing specs. -->

## Impact

- New repository content: services (sync worker, private API, public API, inference service), ML pipeline jobs, frontend, Helm charts, Terraform modules, CI workflows, README.
- External dependencies: Strava API (OAuth app registration), optional Garmin Connect partner API, an LLM API, Cloudflare or Route 53 DNS, a VM provider (Hetzner, DigitalOcean or Oracle Cloud free tier), Let's Encrypt.
- Data: private health data about the owner (workouts, HR, GPS). Public exposure is limited to the sanitized tables by design; this is the main risk the specs constrain.
- Open dataset licences (GoldenCheetah OpenData, FitRec, Kaggle sets, PhysioNet) must be verified before any public use of derived models or results.
- Cost target: roughly 2-4 vCPU, 4-8 GB RAM, 40-80 GB SSD in production; LLM API spend in cents per month.

## Assumptions

- Garmin's Health/Activity API requires partner approval, so Strava and FIT/GPX upload are the guaranteed ingestion paths; Garmin API sync is optional.
- Single owner, single athlete. "Percentiles" on the public dashboard compare the owner against open-dataset populations, not against other users of this platform.
- Backend and ML code in Python (FastAPI); the frontend stack is chosen in design.md.
- Delivery is phased (foundations, ingestion and metrics, ML and coach, public layer); all phases are in scope of this change but ordered in tasks.md.
