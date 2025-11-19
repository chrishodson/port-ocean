# AWS-Serverless
Event-driven integration that routes AWS events into Port using serverless primitives.

This includes a set of scripts to do the initial setup in port and cloudformation templates to set up services within AWS.

## High-level responsibilities

Within Port
- Create a single ingest webhook (`aws_ingest`) that receives routed events
- Create blueprints required for AWS resource types
- Apply mapping rules on the single webhook so each incoming event is translated into the correct blueprint/entity

Within AWS
- Create/validate an SQS queue
- Create an EventBridge rule that captures AWS events and forwards them to SQS
- Deploy a Lambda that reads SQS and forwards enriched events to the single Port webhook

## Supported types
This module depends on the blueprints and mappings in the ocean integration aws-v3.  The files integrations\aws-v3\.port\resources\blueprints.json and integrations\aws-v3\.port\resources\port-app-config.yml hold thos respectively.

## Prerequisites
The environment variable `PORT_API_TOKEN` should be set with the JWT bearer token. (`export PORT_API_TOKEN="Bearer exampletoken"`)
The setup script needs to be run in an environment that has the proper AWS credentials.

# Data flow

The pipeline is: EventBridge -> SQS -> Lambda -> Port (single ingest webhook). The per-type routing inside Port is handl
ed by mapping rules on the single `aws_ingest` webhook (the diagram labels are logical per-type mappings rather than sep
arate webhook endpoints).

```mermaid
flowchart LR
  subgraph AWS
    EC2[EC2 Instance State Changes]
    S3[S3 Events]
    RDS[RDS Events]
    SQSRes[SQS Events]
    EB[(EventBridge Bus)]
    Q[SQS Queue]
  end

  subgraph Serverless
    L[Lambda: port-aws-event-processor]
  end

  subgraph Port
    PWH_LOGICAL[Port Webhook - aws_ingest (logical per-type mappings)]
  end

  EC2 -->|Rule: EC2 state-change| EB
  S3 --> EB
  RDS --> EB
  SQSRes --> EB
  EB -->|Target: SQS| Q
  Q -->|Trigger| L
  L -->|POST to| PWH_LOGICAL
```

