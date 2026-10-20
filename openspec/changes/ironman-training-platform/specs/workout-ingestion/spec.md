## Purpose

Bring the owner's swim, bike and run workouts from Strava and from FIT/GPX files into the platform's database reliably and without duplicates.

## ADDED Requirements

### Requirement: Strava activity sync
The system SHALL ingest the owner's Strava activities via webhook events and a periodic API sync that backfills missed events.

#### Scenario: Webhook creates a workout
- **WHEN** Strava sends a verified "activity created" event for the owner
- **THEN** the system fetches the activity and stores it as a workout

#### Scenario: Unverified webhook rejected
- **WHEN** a webhook request fails Strava's subscription verification or comes from an unknown subscription
- **THEN** the system rejects it and stores nothing

#### Scenario: Missed event recovered
- **WHEN** a webhook event was lost and the periodic sync runs
- **THEN** the missing activity is stored without manual action

### Requirement: File import
The system SHALL accept FIT and GPX file uploads from the owner and store each file's workout data, including Garmin exports.

#### Scenario: Valid FIT file
- **WHEN** the owner uploads a valid FIT file
- **THEN** a workout is created with sport, start time, duration, distance and available HR/power/pace samples

#### Scenario: Corrupt file
- **WHEN** the owner uploads a file that cannot be parsed
- **THEN** the system rejects it with an error naming the problem and stores no partial workout

### Requirement: Idempotent ingestion
The system SHALL store each real-world workout at most once regardless of source or delivery count.

#### Scenario: Same workout from two sources
- **WHEN** a workout arrives via Strava and later via a FIT upload with matching start time and duration
- **THEN** one workout record exists and the richer data is retained

#### Scenario: Duplicate webhook delivery
- **WHEN** the same webhook event is delivered twice
- **THEN** one workout record exists

### Requirement: Queued processing with retry
The system SHALL process ingestion as queued jobs that retry transient failures with backoff and surface permanent failures.

#### Scenario: Strava rate limit
- **WHEN** a fetch fails because Strava rate limits the request
- **THEN** the job is retried later and no data is lost

#### Scenario: Permanent failure visible
- **WHEN** a job exhausts its retries
- **THEN** it is recorded as failed and visible to the owner and in monitoring

### Requirement: Token security
The system SHALL store third-party OAuth tokens encrypted and refresh them before expiry.

#### Scenario: Expired access token
- **WHEN** a sync runs with an expired Strava access token
- **THEN** the system refreshes it and continues without owner action
