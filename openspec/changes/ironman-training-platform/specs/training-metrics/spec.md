## Purpose

Turn stored workouts into training-load and fitness metrics the owner and downstream ML and coaching features can rely on.

## ADDED Requirements

### Requirement: Per-workout training stress
The system SHALL compute a training stress score for every workout using the best available signal for its sport (power, pace or heart rate) and the owner's configured thresholds.

#### Scenario: Bike with power
- **WHEN** a bike workout has power data and the owner's FTP is set
- **THEN** its stress is computed from power relative to FTP

#### Scenario: Fallback to heart rate
- **WHEN** a workout has no power or pace data but has heart rate
- **THEN** stress is computed from heart rate relative to the owner's thresholds and marked as an estimate

#### Scenario: No usable data
- **WHEN** a workout has no signal usable for stress
- **THEN** stress is left unset and the workout is flagged rather than given a fabricated value

### Requirement: Fitness, fatigue and form
The system SHALL compute daily CTL, ATL and TSB from the stress history, including days with no training.

#### Scenario: Rest day decay
- **WHEN** a day has no workouts
- **THEN** CTL and ATL decay for that day and TSB is updated

#### Scenario: Late-arriving workout
- **WHEN** a workout dated in the past is ingested
- **THEN** CTL, ATL and TSB are recomputed from that date forward

### Requirement: Per-sport volume
The system SHALL report weekly and cumulative volume (time, distance, stress) separately for swim, bike and run.

#### Scenario: Weekly summary
- **WHEN** the owner requests the current week's volume
- **THEN** totals per sport and overall are returned

### Requirement: Zones
The system SHALL derive pace, power and heart-rate zones from owner thresholds and report time-in-zone per workout and per week.

#### Scenario: Threshold changed
- **WHEN** the owner updates a threshold
- **THEN** zones for subsequent calculations use the new value and historical zone data remains reproducible from the threshold in effect at the time

### Requirement: Race-goal progress
The system SHALL track progress toward a configured race (date, target finish time, target CTL) and show weeks remaining.

#### Scenario: Goal progress
- **WHEN** a race goal is configured
- **THEN** the owner can see current CTL against the target CTL trajectory and time remaining
