## Purpose

Provision, deploy and operate the whole platform reproducibly from code on a small single-node Kubernetes cluster, locally and in production.

## ADDED Requirements

### Requirement: Infrastructure as code
The system SHALL provision the VM, storage and DNS records with Terraform using remote state, such that a fresh environment can be created from the repository and documented credentials.

#### Scenario: Plan before apply
- **WHEN** infrastructure code changes
- **THEN** CI shows the Terraform plan before any apply

#### Scenario: Rebuild
- **WHEN** the production VM is destroyed
- **THEN** it can be recreated from Terraform and GitOps without manual cluster configuration beyond documented bootstrap secrets

### Requirement: GitOps deployment
The system SHALL deploy all workloads from Helm charts reconciled by ArgoCD from the Git repository.

#### Scenario: Merge to main
- **WHEN** a change to a chart or values merges to the main branch
- **THEN** ArgoCD syncs the cluster to match

#### Scenario: Drift
- **WHEN** a resource is edited manually in the cluster
- **THEN** ArgoCD reports drift and reverts it

### Requirement: Continuous integration
The system SHALL run tests, linting, container builds and chart/Terraform validation in CI on every pull request.

#### Scenario: Failing check
- **WHEN** any CI check fails
- **THEN** the change cannot be merged

### Requirement: Secrets management
The system SHALL keep no secrets in Git and SHALL deliver credentials to workloads through External Secrets.

#### Scenario: Secret scan
- **WHEN** a commit contains a credential
- **THEN** CI fails

### Requirement: TLS ingress and DNS
The system SHALL expose the public and private web endpoints through an ingress with automatically issued and renewed Let's Encrypt certificates, using sslip.io hostnames in development and a custom domain in production.

#### Scenario: Certificate issued
- **WHEN** a hostname is configured on the ingress
- **THEN** a valid certificate is issued without manual steps

#### Scenario: Plain HTTP
- **WHEN** a request arrives over HTTP
- **THEN** it is redirected to HTTPS

### Requirement: Network isolation
The system SHALL restrict network paths between workloads so that the public API cannot reach private services and the inference service is cluster-internal.

#### Scenario: Public API to private API
- **WHEN** the public API attempts to connect to the private API or private database role
- **THEN** the connection is blocked

### Requirement: Data stores
The system SHALL run PostgreSQL with TimescaleDB for workout time-series, metrics, features and separate public tables, and Redis for queues, caching, rate limiting and online features, with persistent storage for PostgreSQL.

#### Scenario: Pod restart
- **WHEN** the PostgreSQL pod restarts
- **THEN** no data is lost

### Requirement: Backup and restore
The system SHALL back up PostgreSQL on a schedule to storage outside the VM and document a tested restore.

#### Scenario: Restore
- **WHEN** a backup is restored to a clean instance
- **THEN** the application operates with the restored data

### Requirement: Observability
The system SHALL collect metrics (Prometheus), dashboards (Grafana) and logs (Loki), and alert on failed ingestion jobs, failed training runs, certificate expiry and resource exhaustion.

#### Scenario: Job failure alert
- **WHEN** the weekly training CronJob fails
- **THEN** an alert is raised

### Requirement: Resource budget
The system SHALL run within 4 vCPU, 8 GB RAM and 80 GB disk in production, and in a local k3d or kind cluster on a 16 GB machine in development.

#### Scenario: Local environment
- **WHEN** a developer runs the documented local setup
- **THEN** the stack starts on a 16 GB laptop with demo data

### Requirement: Documentation
The system SHALL ship a README describing the architecture with diagrams, the privacy-by-design approach, setup steps and a live demo link.

#### Scenario: New reader
- **WHEN** a reader opens the README
- **THEN** they find the architecture diagram, anonymization approach, and a link to the live demo
