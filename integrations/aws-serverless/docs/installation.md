# Installation

## Prerequisites
- Port API credentials (Client ID, Client Secret) with permissions to create blueprints, integrations, and webhooks
- AWS account with permissions to create CloudFormation stacks, SQS, EventBridge, Lambda, and IAM (see policy below)
- AWS CLI configured with credentials (or use IAM role/instance profile)
- Python 3.12+ with dependencies: `pip install -r requirements.txt`

### Required AWS Permissions (example policy)
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "cloudformation:CreateStack",
        "cloudformation:UpdateStack",
        "cloudformation:DescribeStacks",
        "cloudformation:DescribeStackEvents",
        "sqs:CreateQueue",
        "sqs:SetQueueAttributes",
        "sqs:GetQueueAttributes",
        "sqs:GetQueueUrl",
        "events:PutRule",
        "events:PutTargets",
        "events:DescribeRule",
        "lambda:CreateFunction",
        "lambda:UpdateFunctionCode",
        "lambda:UpdateFunctionConfiguration",
        "lambda:GetFunction",
        "lambda:CreateEventSourceMapping",
        "lambda:UpdateEventSourceMapping",
        "iam:CreateRole",
        "iam:AttachRolePolicy",
        "iam:PutRolePolicy",
        "iam:GetRole",
        "iam:PassRole"
      ],
      "Resource": "*"
    }
  ]
}
```

## Standalone (single account)
1. Export credentials:
   ```bash
   export PORT_CLIENT_ID="<id>"
   export PORT_CLIENT_SECRET="<secret>"
   ```
2. Run installer:
   ```bash
   cd integrations/aws-serverless
   python3 install_standalone.py [options]
   ```
   Common examples:
   ```bash
   python3 install_standalone.py                          # defaults
   python3 install_standalone.py --aws-region eu-west-1   # custom region
   python3 install_standalone.py --port-only              # Port setup only, print CFN CLI
   python3 install_standalone.py --dry-run                # no-op preview
   python3 install_standalone.py --event-sources "aws.ec2,aws.s3"
   ```
3. Verify:
   - CloudFormation stack status (default: `port-aws-serverless`)
   - Lambda `port-aws-event-processor` exists and is invoked
   - Blueprints and integration appear in Port

## StackSets (multi-account)
1. Run Port setup once:
   ```bash
   export PORT_CLIENT_ID="<id>"
   export PORT_CLIENT_SECRET="<secret>"
   python3 install_standalone.py --port-only
   ```
2. Create a StackSet using `cloudformation/aws-serverless.template` from the management account.
3. Deploy stack instances with parameters:
   - `PortWebhookUrl`: URL from the installer output (or Port UI)
   - `QueueName`: default `port-aws-events-queue`
   - `LambdaFunctionName`: default `port-aws-event-processor`

## CLI options (installer)
| Option | Default | Description |
| --- | --- | --- |
| `--port-base-url` | `https://api.getport.io` | Port API base URL |
| `--aws-region` | `us-east-1` | AWS region |
| `--integration-id` | `aws-serverless` | Port integration ID |
| `--stack-name` | `port-aws-serverless` | CloudFormation stack name |
| `--queue-name` | `port-aws-events-queue` | SQS queue name |
| `--lambda-function-name` | `port-aws-event-processor` | Lambda name |
| `--webhook` | `aws_ingest` | Webhook ID or URL |
| `--event-sources` | `aws.ec2,aws.s3,aws.rds,aws.sqs,aws.ecs,aws.eks,aws.lambda` | EventBridge sources |
| `--port-only` | `false` | Only Port setup; print CFN CLI |
| `--dry-run` | `false` | Simulate actions |
| `--verify-mappings` | `false` | Compare live Port integration config against local `.port/resources/port-app-config.yml` |

### Webhook and event sources
- `--webhook` supports identifier (`aws_ingest`), full URL, or `/v1/webhooks/<id>` path.
- Narrow sources with `--event-sources "aws.ec2,aws.s3"` if you want fewer events.

## Uninstallation
- Delete the CloudFormation stack: `aws cloudformation delete-stack --stack-name port-aws-serverless`
- Optional: remove the Port integration and blueprints if they are not used elsewhere.
