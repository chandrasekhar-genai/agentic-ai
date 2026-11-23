# Kubernetes deployments

All workloads on the AKS clusters are deployed with GitOps. Argo CD syncs each application from its environment branch. Manual kubectl changes in production are reverted by Argo CD self-heal.

## Promotion

Changes are promoted dev → staging → production through pull requests. Production promotion needs one approval from the service owner and a green staging smoke test.

## Change freeze

A change freeze applies from the 25th of December to the 2nd of January and during the last two business days of each quarter. Emergency fixes during a freeze need incident commander approval.

## Rollback

To roll back, revert the pull request that changed the image tag. Argo CD deploys the previous version within 3 minutes. Do not use kubectl rollout undo in production because Argo CD will reapply the newer version.
