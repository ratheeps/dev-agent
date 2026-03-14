#!/usr/bin/env bash
# ----------------------------------------------------------------
# setup-aws.sh — Bootstrap AWS resources for the Mason memory layer
#
# Usage:
#   ./scripts/setup-aws.sh [--region us-east-1]
#
# Prerequisites:
#   - AWS CLI v2 configured with valid credentials
#   - Node.js >= 18 (for CDK)
#   - Python venv with aws-cdk-lib installed
# ----------------------------------------------------------------
set -euo pipefail

REGION="${1:-us-east-1}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CDK_DIR="${PROJECT_ROOT}/infra/cdk"
POLICY_NAME="devai-memory-policy"

echo "==> Checking AWS CLI configuration..."
if ! aws sts get-caller-identity > /dev/null 2>&1; then
    echo "ERROR: AWS CLI is not configured or credentials are invalid."
    echo "Run 'aws configure' or export AWS_PROFILE first."
    exit 1
fi

ACCOUNT_ID=$(aws sts get-caller-identity --query "Account" --output text)
echo "    Account: ${ACCOUNT_ID}"
echo "    Region:  ${REGION}"

# ----------------------------------------------------------------
# IAM policy
# ----------------------------------------------------------------
echo "==> Creating IAM policy ${POLICY_NAME} (if not exists)..."
POLICY_ARN="arn:aws:iam::${ACCOUNT_ID}:policy/${POLICY_NAME}"

POLICY_DOC=$(cat <<'POLICY'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DevAiDynamoDB",
      "Effect": "Allow",
      "Action": [
        "dynamodb:PutItem",
        "dynamodb:GetItem",
        "dynamodb:Query",
        "dynamodb:DeleteItem",
        "dynamodb:BatchWriteItem",
        "dynamodb:BatchGetItem",
        "dynamodb:DescribeTable"
      ],
      "Resource": [
        "arn:aws:dynamodb:*:*:table/devai-session-memory",
        "arn:aws:dynamodb:*:*:table/devai-episodic-memory",
        "arn:aws:dynamodb:*:*:table/devai-semantic-memory"
      ]
    }
  ]
}
POLICY
)

if aws iam get-policy --policy-arn "${POLICY_ARN}" > /dev/null 2>&1; then
    echo "    Policy already exists — skipping."
else
    aws iam create-policy \
        --policy-name "${POLICY_NAME}" \
        --policy-document "${POLICY_DOC}" \
        --description "Mason memory subsystem DynamoDB access" \
        --region "${REGION}" \
        > /dev/null
    echo "    Policy created."
fi

# ----------------------------------------------------------------
# CDK deploy
# ----------------------------------------------------------------
echo "==> Deploying CDK stack..."
cd "${CDK_DIR}"

# Ensure CDK CLI is available
if ! command -v cdk > /dev/null 2>&1; then
    echo "    Installing AWS CDK CLI..."
    npm install -g aws-cdk
fi

# Bootstrap CDK (idempotent)
cdk bootstrap "aws://${ACCOUNT_ID}/${REGION}" --region "${REGION}" 2>/dev/null || true

cdk deploy DevAiMemoryStack \
    --require-approval never \
    --context "region=${REGION}" \
    --region "${REGION}"

# ----------------------------------------------------------------
# Verify tables
# ----------------------------------------------------------------
echo "==> Verifying DynamoDB tables..."
TABLES=("devai-session-memory" "devai-episodic-memory" "devai-semantic-memory")
ALL_OK=true

for TABLE in "${TABLES[@]}"; do
    STATUS=$(aws dynamodb describe-table \
        --table-name "${TABLE}" \
        --region "${REGION}" \
        --query "Table.TableStatus" \
        --output text 2>/dev/null || echo "NOT_FOUND")
    if [ "${STATUS}" = "ACTIVE" ]; then
        echo "    ${TABLE}: ACTIVE"
    else
        echo "    ${TABLE}: ${STATUS} (expected ACTIVE)"
        ALL_OK=false
    fi
done

if [ "${ALL_OK}" = true ]; then
    echo "==> All tables verified. Setup complete."
else
    echo "==> WARNING: Some tables are not in ACTIVE state. Check the AWS console."
    exit 1
fi
