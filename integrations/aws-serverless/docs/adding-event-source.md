# Adding a New Event Source

Use this checklist to add a new AWS event source (e.g., CloudFront, DynamoDB).

## 1) Decide the event source
- Confirm EventBridge emits the events you need (source name, detail-type).
- If not native, consider EventBridge pipes or custom producers.

## 2) Update Port blueprints
- Edit `.port/resources/blueprints.json` and add a blueprint for the new resource.
- Include identifying properties (e.g., ARN, name, region, accountId) and metadata you will map.
- Keep identifiers stable (ARN or composite key) to avoid churn.

## 3) Update webhook mappings
- Edit `.port/resources/port-app-config.yml` and add a mapping for the new blueprint.
- Extract fields from the EventBridge payload to set `identifier`, `title`, and required properties.
- If shape varies by detail-type, add a `selector` with the matching pattern to scope the mapping.

## 4) Allow the event source through EventBridge
- The integration templates accept a comma list of sources via `SupportedEventSources`.
- Add your source (e.g., `aws.cloudfront`) when running:
  - Standalone: `python3 install_standalone.py --event-sources "aws.ec2,aws.s3,aws.cloudfront"`
  - StackSets: `python3 install_stackset.py --event-sources "aws.ec2,aws.s3,aws.cloudfront" ...`
- If you need a new default, update the CloudFormation template parameter `SupportedEventSources` in `cloudformation/aws-serverless.template`.

## 5) Test locally
- Drop a sample EventBridge payload into `sample_events/` and send via:
  ```bash
  python3 send_sample_event.py <webhook_url> sample_events/your_event.json
  ```
- Verify the entity appears/updates in Port under the new blueprint.

## 6) Roll out
- Re-run `install_standalone.py` (single account) or `install_stackset.py --apply` (multi-account) with the updated `--event-sources` list.
- Confirm EventBridge rule includes the new source and entities are created in Port.
- For updating an existing stack manually, see [`updating.md`](updating.md).

## Gotchas
- Missing identifiers in mappings will create duplicate entities—always set `identifier` deterministically.
- If the event lacks account/region, enrich in the mapping using available fields.
- Large payloads: avoid copying entire `detail` into properties; map only required fields.
