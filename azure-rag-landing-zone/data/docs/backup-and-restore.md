# Backup and restore policy

## Databases

Production Azure SQL and PostgreSQL databases use point-in-time restore with a retention of 35 days. Long-term retention keeps weekly backups for 12 months. Backups are geo-redundant.

The recovery point objective (RPO) for tier-1 services is 15 minutes. The recovery time objective (RTO) for tier-1 services is 4 hours.

## Restore testing

Each service team restores its tier-1 database into an isolated subscription every quarter and records the restore time. A failed restore test is raised as a SEV3 incident.

## Storage accounts

Blob soft delete is enabled for 14 days on all production storage accounts, together with versioning. Immutable storage is used for audit logs.
