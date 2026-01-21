# Data Flow and Mapping

## Pipeline
EventBridge → SQS → Lambda → Port webhook → Blueprints

## Processing steps
1. AWS service emits an event (e.g., EC2 state change).
2. EventBridge rule matches the source and routes to SQS.
3. Lambda is triggered by SQS; it can forward raw events or pre-formatted entities.
4. Lambda POSTs to the Port webhook.
5. Port applies mapping rules from `.port/resources/port-app-config.yml` to create/update entities.

## Entity mapping notes
- Raw EventBridge payloads are transformed via webhook mappings in Port.
- Pre-formatted entities (with `blueprint` and `identifier`) are forwarded as-is.
- Mappings and blueprints live in `.port/resources/` (files: `port-app-config.yml` and `blueprints.json`).
