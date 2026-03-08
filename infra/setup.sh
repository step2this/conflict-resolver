#!/bin/bash
# Deploy the pipeline scheduler via CloudFormation.
#
# Usage:
#   ./infra/setup.sh <instance-id> [notification-email] [region]
#   ./infra/setup.sh i-032e18c24b66bb182
#   ./infra/setup.sh i-032e18c24b66bb182 you@example.com us-east-1

set -euo pipefail

INSTANCE_ID="${1:?Usage: $0 <instance-id> [notification-email] [region]}"
NOTIFICATION_EMAIL="${2:-}"
REGION="${3:-us-east-1}"

STACK_NAME="conflict-resolver-pipeline"
S3_BUCKET="conflict-digest"
S3_KEY="lambda/pipeline-scheduler.zip"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Deploying pipeline scheduler ==="
echo "Instance: $INSTANCE_ID"
echo "Region:   $REGION"
echo "Stack:    $STACK_NAME"
[ -n "$NOTIFICATION_EMAIL" ] && echo "Notify:   $NOTIFICATION_EMAIL"
echo ""

# 1. Package Lambda zip
echo "Packaging Lambda..."
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT
cp "$SCRIPT_DIR/pipeline_scheduler.py" "$TMPDIR/lambda_function.py"
cd "$TMPDIR" && zip -j function.zip lambda_function.py && cd - >/dev/null

# 2. Upload to S3
echo "Uploading to s3://$S3_BUCKET/$S3_KEY..."
aws s3 cp "$TMPDIR/function.zip" "s3://$S3_BUCKET/$S3_KEY" --region "$REGION"

# 3. Deploy CloudFormation stack
echo "Deploying CloudFormation stack..."
PARAMS="InstanceId=$INSTANCE_ID"
if [ -n "$NOTIFICATION_EMAIL" ]; then
    PARAMS="$PARAMS NotificationEmail=$NOTIFICATION_EMAIL"
fi

aws cloudformation deploy \
    --template-file "$SCRIPT_DIR/template.yaml" \
    --stack-name "$STACK_NAME" \
    --parameter-overrides $PARAMS \
    --capabilities CAPABILITY_NAMED_IAM \
    --region "$REGION"

# 4. Force Lambda to pick up new code from S3
echo "Updating Lambda function code..."
aws lambda update-function-code \
    --function-name conflict-resolver-pipeline \
    --s3-bucket "$S3_BUCKET" \
    --s3-key "$S3_KEY" \
    --region "$REGION" >/dev/null

echo ""
echo "=== Deployment complete ==="
echo ""
echo "Schedules: 6:00 AM UTC and 6:00 PM UTC"
echo "Lambda:    conflict-resolver-pipeline"
echo "Logs:      aws logs tail /aws/lambda/conflict-resolver-pipeline --follow"
echo ""
echo "To test manually:"
echo "  aws lambda invoke --function-name conflict-resolver-pipeline /dev/stdout"
