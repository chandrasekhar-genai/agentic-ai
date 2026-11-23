# Production access

Contoso Platform uses just-in-time access. Nobody holds standing write access to production subscriptions.

## Requesting access

Request the "Production Operator" role through Microsoft Entra Privileged Identity Management (PIM). Activation requires a ticket number and a business justification. The maximum activation duration is 8 hours.

Activations are approved by the owning service's on-call lead. During a SEV1 incident, the incident commander may approve activation for any responder.

## Break-glass accounts

Two break-glass accounts exist for tenant-wide outages. Their credentials are stored in a sealed envelope in the Dubai office safe and in the secondary site. Every break-glass sign-in triggers a SEV2 security alert and must be reviewed by the security team within 24 hours.

## Access reviews

Eligible role assignments are reviewed every quarter. Assignments that are not confirmed by the manager are removed automatically.
