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

Deploy across multiple AWS accounts from a central management account.

### Prerequisites
- AWS Organization with StackSets trusted access enabled
- Management account (or delegated admin for StackSets)
- Port webhook URL (from running `install_standalone.py --port-only`)
- Python 3.12+ with dependencies: `pip install -r requirements.txt`

### Setup
1. **Run Port setup once** (from anywhere with Port credentials):
   ```bash
   export PORT_CLIENT_ID="<id>"
   export PORT_CLIENT_SECRET="<secret>"
   python3 install_standalone.py --port-only
   ```
   Copy the webhook URL from the output.

2. **Run preflight checks** (from management account, in the integration directory):
   ```bash
   python3 install_stackset.py \
     --webhook-url "https://ingest.getport.io/your-webhook" \
     --target-ous "ou-xxxx-yyyyyyyy" \
     --regions "us-east-1 us-west-2"
   ```
   This validates your setup without making any changes.

3. **Deploy with `--apply`** once preflight passes:
   ```bash
   python3 install_stackset.py \
     --webhook-url "https://ingest.getport.io/your-webhook" \
     --target-ous "ou-xxxx-yyyyyyyy" \
     --regions "us-east-1 us-west-2" \
     --apply
   ```
   This creates the StackSet and deploys stack instances to target OUs.

### CLI Options (install_stackset.py)
| Option | Default | Required | Description |
| --- | --- | --- | --- |
| `--webhook-url` | — | Yes | Port ingest webhook URL (https://…) |
| `--stackset-name` | `port-aws-serverless` | — | StackSet name |
| `--template-url` | GitHub main branch | — | CloudFormation template URL |
| `--queue-name` | `port-aws-events-queue` | — | SQS queue name |
| `--lambda-name` | `port-aws-event-processor` | — | Lambda function name |
| `--event-sources` | `aws.ec2,aws.s3,aws.ecs` | — | Comma-separated EventBridge sources |
| `--permission-model` | `service-managed` | — | `service-managed` or `self-managed` |
| `--target-ous` | — | service-managed | Comma-separated OU IDs for deployment |
| `--target-accounts` | — | self-managed | Comma-separated account IDs for deployment |
| `--regions` | — | Yes | Space or comma-separated regions for deployment |
| `--admin-role-arn` | — | self-managed | Admin role ARN for self-managed StackSets |
| `--execution-role-name` | `AWSCloudFormationStackSetExecutionRole` | self-managed | Execution role name in target accounts |
| `--apply` | `false` | — | If set, creates/updates StackSet and stack instances |

For full help and advanced options, run `python3 install_stackset.py --help`.

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

### Extending to new event sources
See [`docs/adding-event-source.md`](adding-event-source.md) for how to add blueprints, mappings, and EventBridge sources.

## Uninstallation
- Delete the CloudFormation stack: `aws cloudformation delete-stack --stack-name port-aws-serverless`
- Optional: remove the Port integration and blueprints if they are not used elsewhere.
