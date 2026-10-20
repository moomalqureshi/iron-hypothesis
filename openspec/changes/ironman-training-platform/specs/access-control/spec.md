## Purpose

Restrict who can see what: full access for the owner, scoped read-only access for invited viewers and anonymized-only access for the public.

## ADDED Requirements

### Requirement: Owner authentication
The system SHALL authenticate the owner through an OAuth provider and require a second factor.

#### Scenario: Login without second factor
- **WHEN** the owner completes OAuth but not 2FA
- **THEN** no private data or action is accessible

#### Scenario: Non-owner account
- **WHEN** a different OAuth identity signs in
- **THEN** access is denied

### Requirement: Viewer share links
The system SHALL let the owner create signed, read-only share links with a defined scope and expiry, and revoke them at any time.

#### Scenario: Valid link
- **WHEN** a viewer opens an unexpired, unrevoked link
- **THEN** they see only the scoped data, read-only

#### Scenario: Revoked link
- **WHEN** the owner revokes a link
- **THEN** subsequent requests with it are denied

#### Scenario: Tampered link
- **WHEN** a link's signature or scope is altered
- **THEN** it is rejected

#### Scenario: Write attempt
- **WHEN** a viewer attempts any state-changing action
- **THEN** it is denied

### Requirement: Role enforcement at the API
The system SHALL enforce roles on the server for every private endpoint, independent of the UI.

#### Scenario: Unauthenticated request
- **WHEN** a request without credentials calls a private endpoint
- **THEN** it receives an authentication error and no data

### Requirement: Public role
The system SHALL give unauthenticated users access only to the anonymized public dashboard and its public API.

#### Scenario: Public requests private path
- **WHEN** an unauthenticated user requests a private endpoint
- **THEN** it is denied

### Requirement: Demo mode
The system SHALL offer a demo mode that serves only synthetic data and is clearly labelled as such.

#### Scenario: Demo visitor
- **WHEN** a visitor opens demo mode
- **THEN** all shown data is synthetic, derived from none of the owner's records, and labelled "demo"

### Requirement: Audit of access
The system SHALL log owner logins, share-link creation and revocation, and viewer link use.

#### Scenario: Link used
- **WHEN** a share link is used
- **THEN** an audit entry records link identifier and time
