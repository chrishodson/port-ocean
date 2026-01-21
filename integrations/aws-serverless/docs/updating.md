# Updating the Deployment

## Manual CloudFormation update (single account)
If you change the template or parameters, update the existing stack instead of reinstalling:

```bash
cd port-ocean/integrations/aws-serverless

aws cloudformation update-stack \
  --stack-name port-aws-serverless \
  --template-body file://cloudformation/aws-serverless.template \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameters \
      ParameterKey=PortWebhookUrl,ParameterValue="https://ingest.getport.io/..." \
      ParameterKey=QueueName,UsePreviousValue=true \
      ParameterKey=LambdaFunctionName,UsePreviousValue=true \
      ParameterKey=SupportedEventSources,UsePreviousValue=true \
      ParameterKey=LambdaRuntime,UsePreviousValue=true \
      ParameterKey=Handler,UsePreviousValue=true
```

Notes:
- Update `PortWebhookUrl` if it changed; keep other parameters with `UsePreviousValue=true` unless you intend to change them.
- Watch stack events for progress/errors: `aws cloudformation describe-stack-events --stack-name port-aws-serverless`.
- For StackSets, use `aws cloudformation update-stack-set` with the same template and parameters.
