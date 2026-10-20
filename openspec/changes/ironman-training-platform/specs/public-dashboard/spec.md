## Purpose

Let anyone view the owner's anonymized training progress without logging in, as a shareable portfolio demonstration.

## ADDED Requirements

### Requirement: Anonymous access
The system SHALL serve the public dashboard to unauthenticated visitors over HTTPS.

#### Scenario: Open visit
- **WHEN** a visitor opens the public URL without logging in
- **THEN** the dashboard loads from sanitized data only

### Requirement: Dashboard content
The public dashboard SHALL show training volume trends by sport, fitness trend, progress toward the race goal and percentile comparisons.

#### Scenario: Trends displayed
- **WHEN** the dashboard loads
- **THEN** it shows weekly volume per sport, a fitness trend line and goal progress

### Requirement: Read-only public API
The system SHALL expose a public API that supports only read operations on sanitized data.

#### Scenario: Write method
- **WHEN** a POST, PUT, PATCH or DELETE is sent to the public API
- **THEN** it is rejected

### Requirement: Abuse protection
The system SHALL rate limit public requests.

#### Scenario: Excess requests
- **WHEN** a client exceeds the public rate limit
- **THEN** further requests receive a rate-limit response until the window resets

### Requirement: Freshness and disclaimer
The system SHALL show when public data was last refreshed and the not-medical-advice disclaimer.

#### Scenario: Last updated
- **WHEN** the dashboard loads
- **THEN** the last sanitization time and the disclaimer are visible

### Requirement: Responsive display
The system SHALL render usably on phone and desktop widths.

#### Scenario: Mobile
- **WHEN** viewed on a narrow screen
- **THEN** charts and navigation remain usable without horizontal page scrolling
