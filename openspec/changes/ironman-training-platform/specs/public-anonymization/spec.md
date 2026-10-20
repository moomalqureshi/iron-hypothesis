## Purpose

Ensure nothing identifying the owner is ever reachable from the public side, by sanitizing data server-side into separate public tables.

## ADDED Requirements

### Requirement: Identity separation
The system SHALL store personal identity data separately from training data and SHALL use only pseudonymous identifiers in public data.

#### Scenario: Public record content
- **WHEN** a public record is inspected
- **THEN** it holds no name, email, OAuth or Strava identifiers, or any key that joins back to the identity store

### Requirement: Location privacy
The system SHALL NOT expose raw GPS data publicly. Public output SHALL either omit maps or show routes with start and end regions removed or fuzzed beyond a minimum radius.

#### Scenario: Route shown
- **WHEN** a public view includes a route
- **THEN** the first and last segments within the configured radius are removed and no coordinate is stored at original precision

#### Scenario: Home location
- **WHEN** many workouts start at the same place
- **THEN** that area is never recoverable from public data

### Requirement: Field coarsening
The system SHALL coarsen public fields: age to a bracket, timestamps to day level, and heart rate omitted when the owner has set it hidden.

#### Scenario: Timestamps
- **WHEN** a public workout is stored
- **THEN** it carries a date but no time of day

#### Scenario: HR hidden
- **WHEN** the owner has hidden heart rate
- **THEN** no heart-rate value or HR-derived zone appears in public data

### Requirement: Relative statistics
The system SHALL present public performance as trends and percentiles against reference populations rather than raw absolute values where raw values would aid re-identification.

#### Scenario: Percentile display
- **WHEN** a public metric is shown
- **THEN** it is expressed as percentile or trend relative to the reference data

### Requirement: Server-side sanitization job
The system SHALL populate public tables through a scheduled job that reads private data and writes only sanitized output, and the public API SHALL read only those tables.

#### Scenario: Public API database access
- **WHEN** the public API's database credentials attempt to read a private table
- **THEN** the database denies the read

#### Scenario: Owner deletes a workout
- **WHEN** the owner deletes a workout
- **THEN** its sanitized public counterpart is removed on the next job run at the latest

### Requirement: Privacy regression tests
The system SHALL include automated tests that fail the build if sanitized output contains disallowed fields or precision.

#### Scenario: Leaky change
- **WHEN** a change causes a public table to contain a raw GPS point or an exact timestamp
- **THEN** CI fails
