# Troubleshooting

## Quick checks
1) CloudFormation stack events: look for CREATE/UPDATE failures.
2) Lambda logs: `aws logs tail /aws/lambda/port-aws-event-processor --follow`.
3) SQS queue: confirm messages arrive and are dequeued.
4) Port webhook: verify events reach Port (check integration activity).

## Common issues
- **Lambda not triggering**: ensure EventSourceMapping is enabled; check SQS has messages; verify Lambda role permissions.
- **Events not in Port**: confirm webhook URL in Lambda env; check Lambda logs for HTTP errors; ensure integration is active in Port UI.
- **CloudFormation failure**: usually IAM/permissions or name conflicts; review stack events for specific resource errors.
- **Wrong entity types created**: verify mapping rules in `.port/resources/port-app-config.yml` match incoming event structure; use `--verify-mappings` flag during install.
- **Missing blueprints**: ensure blueprints in `.port/resources/blueprints.json` were created during installation; re-run with `--port-only` if needed.

## Verifying end-to-end flow
- EventBridge metrics show matched events.
- SQS queue depth increases then drains.
- Lambda invocations increase without errors.
- Port entities update for the expected blueprints.

## Uninstall
- Delete the CloudFormation stack.
- Optionally remove the Port integration and blueprints if unused elsewhere.
