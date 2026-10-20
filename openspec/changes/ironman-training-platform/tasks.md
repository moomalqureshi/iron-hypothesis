## 1. Repository and local environment

- [x] 1.1 Create repository layout (`src/ironman/`, `web/`, `charts/`, `scripts/`, `docs/`) with Python tooling (pyproject, ruff, pytest) and a pre-commit config; `terraform/` and `argocd/` are added with the deployment work
- [x] 1.2 Add a k3d cluster script and Makefile targets that start the stack locally with demo data
- [x] 1.3 Add GitHub Actions workflow running lint and tests on pull requests
- [x] 1.4 Add secret scanning to CI

## 2. Data layer

- [x] 2.1 Deploy PostgreSQL with TimescaleDB via Helm with a persistent volume (local values; production values deferred)
- [x] 2.2 Create migrations for `private` schema: identity, workouts, workout samples (hypertable), daily metrics, thresholds, race goal, plans, share links, audit log
- [x] 2.3 Create `public` schema migrations and DB roles: private-API role, sync role, public-API role with `SELECT` on `public` only
- [x] 2.4 Add a test asserting the public role is denied reads on every `private` table
- [x] 2.5 Deploy Redis with AOF persistence and set resource limits

## 3. Workout ingestion

- [x] 3.1 Implement Strava OAuth connection with encrypted token storage and refresh
- [x] 3.2 Implement the verified Strava webhook endpoint and enqueue activity jobs
- [x] 3.3 Implement sync worker with retry/backoff, rate-limit handling and failed-job recording
- [x] 3.4 Implement periodic backfill sync
- [x] 3.5 Implement FIT and GPX parsers and the authenticated upload endpoint with clear parse errors
- [x] 3.6 Implement cross-source de-duplication and richer-data merge
- [x] 3.7 Write tests for duplicate delivery, corrupt files, expired tokens and rate limits

## 4. Training metrics

- [x] 4.1 Implement per-workout stress for power, pace and HR with estimate flags and no-data flagging
- [x] 4.2 Implement daily CTL/ATL/TSB with rest-day decay and recompute-from-date for late workouts
- [x] 4.3 Implement per-sport weekly and cumulative volume
- [x] 4.4 Implement thresholds, zone derivation and time-in-zone with threshold history
- [x] 4.5 Implement race goal and progress against target CTL trajectory
- [x] 4.6 Add metrics endpoints to the private API and unit tests with fixed reference data

## 5. Access control

- [ ] 5.1 Implement OIDC login restricted to the owner identity and TOTP second factor with server-side sessions (password + TOTP is implemented; the OIDC provider step is not)
- [x] 5.2 Implement role enforcement dependency on all private endpoints and tests for unauthenticated access
- [x] 5.3 Implement signed viewer share links with scope, expiry and revocation, read-only enforcement and tamper tests
- [x] 5.4 Implement audit logging for logins and link create/revoke/use
- [x] 5.5 Implement synthetic data generator and labelled demo mode

## 6. Anonymization and public API

- [x] 6.1 Define the column allowlist mapping from private to public tables
- [x] 6.2 Implement keyed-HMAC pseudonymous IDs with the key supplied via secrets
- [x] 6.3 Implement the sanitize CronJob: full rebuild, day-level dates, age brackets, optional HR hiding, no GPS in first release
- [x] 6.4 Implement percentile computation against reference population data
- [x] 6.5 Implement the read-only public API using the public DB role, with rate limiting via Redis
- [x] 6.6 Add privacy regression tests (no identity fields, no exact timestamps, no coordinates, deletion propagation) and run them in CI

## 7. Web application

- [x] 7.1 Scaffold the web app as static HTML/JS served by nginx with owner, viewer and public views
- [x] 7.2 Build owner dashboard: workouts, CTL/ATL/TSB, volume, zones, goal progress
- [x] 7.3 Build share-link management UI and viewer read-only views
- [x] 7.4 Build public dashboard with trends, percentiles, last-updated and disclaimer, responsive down to phone width
- [x] 7.5 Build plan, prediction and anomaly views with the disclaimer

## 8. ML pipeline

- [ ] 8.1 Document source and licence for GoldenCheetah OpenData, FitRec, race results, Kaggle Fitbit and PhysioNet, and decide which are usable for public results
- [ ] 8.2 Implement dataset download/prep scripts and shared feature engineering
- [ ] 8.3 Train and evaluate race-time prediction (LightGBM) with uncertainty and insufficient-data behaviour (a baseline pace estimator with a range is in `analysis.py`; the trained model is not)
- [x] 8.4 Implement CTL forecast for a planned load
- [ ] 8.5 Train overtraining-risk model with contributing-factor output (a rule-based baseline with factors is in `analysis.py`; the trained model is not)
- [ ] 8.6 Train Isolation Forest anomaly detection including HR drift (Isolation Forest on workout features is in `analysis.py`; the `hr_drift` function is not yet wired into it)
- [ ] 8.7 Deploy MLflow with tracking and registry; log data version, params and metrics per run
- [ ] 8.8 Implement weekly training CronJobs with non-regression promotion gate on a time-based hold-out
- [ ] 8.9 Implement the FastAPI inference service, registry model reload and Redis online features
- [ ] 8.10 Add NetworkPolicy limiting inference access to the private API

## 9. AI coach

- [x] 9.1 Define the weekly plan JSON schema and prompt builder using aggregates only
- [x] 9.2 Implement the LLM client with bounded retries, timeouts and rate limiting
- [x] 9.3 Implement the deterministic validator: load cap (default 10%), rest minimum, risk-based reduction, adjustment recording
- [x] 9.4 Store plans with their input snapshot and expose generate/list endpoints
- [x] 9.5 Add tests with a stubbed LLM for malformed output, outage, over-cap plans and prompt contents containing no identity or coordinates
- [ ] 9.6 Log LLM token usage and cost per plan generation

## 10. Infrastructure and delivery

- [ ] 10.1 Write Terraform for VM, volume, firewall and Cloudflare DNS with remote state, plus cloud-init that installs k3s and ArgoCD (deferred: local-only iteration)
- [ ] 10.2 Add CI jobs for `terraform fmt`, `validate` and plan output on pull requests (deferred: local-only iteration)
- [x] 10.3 Write Helm charts for each service and CronJob with resource requests and limits (private API, public API, sync worker, web, data stores, sanitize and Strava-sync CronJobs; inference service and training CronJobs follow task group 8)
- [ ] 10.4 Set up ArgoCD app-of-apps with automated sync, self-heal and prune (deferred: local-only iteration)
- [ ] 10.5 Install ingress, cert-manager (HTTP-01 for sslip.io, DNS-01 for custom domain) and HTTPS redirect (ingress-nginx on kind is installed; TLS is deferred)
- [ ] 10.6 Install External Secrets and a secret store; wire all workload credentials through it (deferred: local-only iteration)
- [ ] 10.7 Add NetworkPolicies isolating public API from private services (deferred: local-only iteration)
- [ ] 10.8 Install kube-prometheus-stack and Loki with tuned retention; add alerts for failed ingestion, failed training, certificate expiry and resource pressure (deferred: local-only iteration)
- [ ] 10.9 Add nightly pg_dump CronJob to object storage and perform and document a restore drill (deferred: local-only iteration)
- [ ] 10.10 Build container images in CI and push to a registry, with image tags updated in chart values (deferred: local-only iteration)

## 11. Launch and documentation

- [ ] 11.1 Deploy to production on sslip.io and run the privacy regression suite and restore drill (deferred: local-only iteration)
- [ ] 11.2 Switch to the custom domain (deferred: local-only iteration)
- [ ] 11.3 Verify Strava API terms for publishing derived data and confirm dataset licences before public launch
- [x] 11.4 Write the README: architecture diagram, privacy-by-design explanation, local setup and not-medical-advice disclaimer (live demo link is added with deployment)
