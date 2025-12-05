#!/usr/bin/env python3
"""Install AWS StackSets deployment for the AWS-Serverless Port integration.

This script performs preflight checks and can optionally create the StackSet and
stack instances. It never auto-remediates; if a gap is detected, it reports the
required manual action and exits non-zero.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from typing import Iterable, List, Optional

import boto3
from botocore.exceptions import ClientError

TEMPLATE_URL_DEFAULT = (
    "https://raw.githubusercontent.com/port-labs/port-ocean/main/"
    "integrations/aws-serverless/cloudformation/aws-serverless.template"
)
SERVICE_PRINCIPAL = "stacksets.cloudformation.amazonaws.com"


@dataclass
class PreflightIssue:
    level: str
    message: str
    remediation: str


@dataclass
class PreflightResult:
    issues: List[PreflightIssue] = field(default_factory=list)

    def add(self, level: str, message: str, remediation: str) -> None:
        self.issues.append(PreflightIssue(level=level, message=message, remediation=remediation))

    @property
    def has_errors(self) -> bool:
        return any(i.level == "error" for i in self.issues)

    def render(self) -> str:
        lines: List[str] = []
        for issue in self.issues:
            lines.append(f"[{issue.level.upper()}] {issue.message}")
            lines.append(f"    Action: {issue.remediation}")
        return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preflight and deploy AWS StackSet for Port AWS Serverless integration")
    parser.add_argument("--webhook-url", required=True, help="Port ingest webhook URL (https://…)")
    parser.add_argument("--stackset-name", default="port-aws-serverless", help="StackSet name")
    parser.add_argument("--template-url", default=TEMPLATE_URL_DEFAULT, help="CloudFormation template URL")
    parser.add_argument("--queue-name", default="port-aws-events-queue", help="SQS queue name")
    parser.add_argument("--lambda-name", default="port-aws-event-processor", help="Lambda function name")
    parser.add_argument("--event-sources", default="aws.ec2,aws.s3,aws.ecs", help="Comma-separated EventBridge sources")
    parser.add_argument("--permission-model", choices=["service-managed", "self-managed"], default="service-managed", help="StackSets permission model")
    parser.add_argument("--admin-role-arn", help="Admin role ARN (self-managed only)")
    parser.add_argument("--execution-role-name", default="AWSCloudFormationStackSetExecutionRole", help="Execution role name in target accounts (self-managed)")
    parser.add_argument("--target-ous", help="Comma-separated OU IDs for deployment (service-managed)")
    parser.add_argument("--target-accounts", help="Comma-separated account IDs for deployment (self-managed)")
    parser.add_argument("--regions", required=True, help="Space-separated or comma-separated regions for deployment")
    parser.add_argument("--apply", action="store_true", help="If set, creates/updates StackSet and stack instances after preflight")
    return parser.parse_args()


def _split_csv(val: Optional[str]) -> List[str]:
    if not val:
        return []
    return [v.strip() for v in val.replace(" ", "").split(",") if v.strip()]


def preflight(args: argparse.Namespace, sts, orgs, iam, cfn) -> PreflightResult:
    result = PreflightResult()

    # Basic webhook validation
    if not args.webhook_url.startswith("http"):
        result.add(
            "error",
            "Webhook URL must start with http/https",
            "Pass a full Port ingest webhook URL (https://ingest.getport.io/…)",
        )

    # Caller identity
    try:
        identity = sts.get_caller_identity()
        account_id = identity.get("Account")
    except ClientError as exc:
        result.add("error", f"STS get_caller_identity failed: {exc}", "Verify AWS credentials and permissions")
        return result

    # Permission model specifics
    if args.permission_model == "service-managed":
        try:
            org = orgs.describe_organization()["Organization"]
            management_account_id = org.get("MasterAccountId") or org.get("ManagementAccountId")
            if account_id != management_account_id:
                # Allow delegated admin
                delegated = orgs.list_delegated_administrators(ServicePrincipal=SERVICE_PRINCIPAL)
                delegated_ids = {d["Id"] for d in delegated.get("DelegatedAdministrators", [])}
                if account_id not in delegated_ids:
                    result.add(
                        "error",
                        "Caller is not the management account or a delegated admin for StackSets",
                        "Use the management account or register this account as a delegated admin for StackSets",
                    )
        except ClientError as exc:
            result.add("error", f"Failed to describe organization: {exc}", "Ensure AWS Organizations is enabled and caller can access it")
        else:
            try:
                access = orgs.list_aws_service_access_for_organization()
                principals = {s.get("ServicePrincipal") for s in access.get("EnabledServicePrincipals", [])}
                if SERVICE_PRINCIPAL not in principals:
                    result.add(
                        "error",
                        "StackSets trusted access is not enabled for AWS Organizations",
                        "Enable trusted access for AWS CloudFormation StackSets in the management account",
                    )
            except ClientError as exc:
                result.add("error", f"Failed to check trusted access: {exc}", "Ensure org:ListAWSServiceAccessForOrganization permission")
    else:
        if not args.admin_role_arn:
            result.add(
                "error",
                "Admin role ARN is required for self-managed StackSets",
                "Pass --admin-role-arn for the StackSets admin role",
            )
        else:
            try:
                iam.get_role(RoleName=args.admin_role_arn.split("/")[-1])
            except ClientError as exc:
                result.add(
                    "warning",
                    f"Unable to verify admin role ARN ({args.admin_role_arn}): {exc}",
                    "Ensure the admin role exists and the caller can assume it",
                )
        if not args.target_accounts:
            result.add(
                "error",
                "Target accounts are required for self-managed StackSets",
                "Pass --target-accounts as a comma-separated list",
            )

    # CloudFormation visibility check
    try:
        cfn.list_stack_sets(MaxResults=1)
    except ClientError as exc:
        result.add(
            "warning",
            f"CloudFormation StackSets visibility check failed: {exc}",
            "Ensure cloudformation:ListStackSets permission in the chosen permission model",
        )

    # Target scope checks
    regions = _split_csv(args.regions) if "," in args.regions else args.regions.split()
    if not regions:
        result.add("error", "At least one region is required", "Provide regions via --regions")

    if args.permission_model == "service-managed" and not _split_csv(args.target_ous):
        result.add(
            "warning",
            "No target OUs provided; no stack instances will be created",
            "Pass --target-ous for the Organizational Units you want to target",
        )

    return result


def create_stackset_and_instances(args: argparse.Namespace, cfn, regions: List[str]) -> None:
    parameters = [
        {"ParameterKey": "PortWebhookUrl", "ParameterValue": args.webhook_url},
        {"ParameterKey": "QueueName", "ParameterValue": args.queue_name},
        {"ParameterKey": "LambdaFunctionName", "ParameterValue": args.lambda_name},
        {"ParameterKey": "SupportedEventSources", "ParameterValue": args.event_sources},
    ]

    stackset_kwargs = {
        "StackSetName": args.stackset_name,
        "TemplateURL": args.template_url,
        "Parameters": parameters,
        "Capabilities": ["CAPABILITY_NAMED_IAM"],
        "PermissionModel": "SERVICE_MANAGED" if args.permission_model == "service-managed" else "SELF_MANAGED",
    }

    if args.permission_model == "self-managed":
        stackset_kwargs["AdministrationRoleARN"] = args.admin_role_arn
        stackset_kwargs["ExecutionRoleName"] = args.execution_role_name

    try:
        cfn.create_stack_set(**stackset_kwargs)
        print(f"Created StackSet {args.stackset_name}")
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "NameAlreadyExistsException":
            print(f"StackSet {args.stackset_name} already exists; will reuse it")
        else:
            raise

    # Create stack instances if targets provided
    target_ous = _split_csv(args.target_ous)
    target_accounts = _split_csv(args.target_accounts)
    if args.permission_model == "service-managed" and not target_ous:
        print("No target OUs provided; skipping stack instance creation")
        return
    if args.permission_model == "self-managed" and not target_accounts:
        print("No target accounts provided; skipping stack instance creation")
        return

    instance_kwargs = {
        "StackSetName": args.stackset_name,
        "Regions": regions,
        "ParameterOverrides": parameters,
    }
    if args.permission_model == "service-managed":
        instance_kwargs["DeploymentTargets"] = {"OrganizationalUnitIds": target_ous}
    else:
        instance_kwargs["DeploymentTargets"] = {"Accounts": target_accounts}

    op = cfn.create_stack_instances(**instance_kwargs)
    op_id = op.get("OperationId")
    print(f"Started stack instances operation: {op_id}")
    print(f"\nTo check status: aws cloudformation describe-stack-set-operation --stack-set-name {args.stackset_name} --operation-id {op_id}")
    print(f"To list instances: aws cloudformation list-stack-instances --stack-set-name {args.stackset_name}")


def main() -> int:
    args = parse_args()
    regions = _split_csv(args.regions) if "," in args.regions else args.regions.split()

    sts = boto3.client("sts")
    orgs = boto3.client("organizations")
    iam = boto3.client("iam")
    cfn = boto3.client("cloudformation")

    pre = preflight(args, sts, orgs, iam, cfn)
    if pre.issues:
        print(pre.render())
    if pre.has_errors:
        print("Preflight failed; no actions were taken.")
        return 1

    if not args.apply:
        print("Preflight passed. Re-run with --apply to create the StackSet and instances.")
        return 0

    create_stackset_and_instances(args, cfn, regions)
    return 0


if __name__ == "__main__":
    sys.exit(main())
