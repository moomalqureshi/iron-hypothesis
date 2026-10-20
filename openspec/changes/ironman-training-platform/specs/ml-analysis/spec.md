## Purpose

Provide predictive and anomaly-detection insights from historical training data, using models pretrained on open datasets and fine-tuned on the owner's data.

## ADDED Requirements

### Requirement: Race-time prediction
The system SHALL predict the owner's finish time for the configured race with an uncertainty range.

#### Scenario: Prediction available
- **WHEN** enough history exists
- **THEN** a predicted finish time with a range and the model version is returned

#### Scenario: Insufficient data
- **WHEN** the owner's history is below the minimum required
- **THEN** the system returns an explicit "insufficient data" result rather than a prediction

### Requirement: Fitness forecast
The system SHALL forecast CTL for the weeks until the race given a planned load.

#### Scenario: Forecast for a plan
- **WHEN** the owner views a generated plan
- **THEN** projected CTL/TSB at race day is shown

### Requirement: Overtraining risk
The system SHALL produce a risk level from recent load, recovery signals and trends.

#### Scenario: Risk rising
- **WHEN** load ramps rapidly with falling form
- **THEN** the risk level increases and the contributing factors are listed

### Requirement: Anomaly detection
The system SHALL flag anomalous workouts such as abnormal heart-rate drift relative to the owner's history.

#### Scenario: HR drift
- **WHEN** a workout shows heart rate drifting far outside the owner's norm for similar effort
- **THEN** it is flagged with the reason

### Requirement: Scheduled retraining and registry
The system SHALL retrain models weekly, record each run with metrics and data version in a model registry, and promote a new model only if it does not regress against the current one on held-out data.

#### Scenario: Regression blocks promotion
- **WHEN** a newly trained model performs worse than the current model on validation
- **THEN** the current model stays in production and the failure is recorded

#### Scenario: Reproducibility
- **WHEN** a model version is inspected
- **THEN** its training data version, parameters and metrics are retrievable

### Requirement: Open dataset provenance
The system SHALL record the source and licence of every open dataset used for pretraining and SHALL NOT publish models or results derived from a dataset whose licence forbids it.

#### Scenario: Licence recorded
- **WHEN** a dataset is added to the pipeline
- **THEN** its licence and source are recorded and reviewed before public use

### Requirement: Inference service
The system SHALL serve predictions through an internal service that is not reachable from the public internet.

#### Scenario: External access
- **WHEN** a request to the inference service originates outside the cluster
- **THEN** it cannot reach the service
