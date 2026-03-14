#!/usr/bin/env bash
# Deploy Mason infrastructure using OpenTofu.
#
# Usage:
#   ./scripts/deploy.sh [staging|production]
#   ./scripts/deploy.sh staging plan    # plan only
#   ./scripts/deploy.sh production apply # apply
#
# Prerequisites:
#   - AWS CLI configured with appropriate credentials
#   - OpenTofu installed (https://opentofu.org/docs/intro/install)

set -euo pipefail

ENVIRONMENT="${1:-staging}"
ACTION="${2:-apply}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TOFU_DIR="$PROJECT_ROOT/infra/tofu"
TFVARS_FILE="$TOFU_DIR/envs/$ENVIRONMENT/terraform.tfvars"

echo "=== Mason Deployment ==="
echo "Environment: $ENVIRONMENT"
echo "Action:      $ACTION"
echo "Tofu dir:    $TOFU_DIR"
echo ""

# Verify prerequisites
command -v aws >/dev/null 2>&1 || { echo "ERROR: aws CLI not found"; exit 1; }
command -v tofu >/dev/null 2>&1 || { echo "ERROR: tofu not found. Install: https://opentofu.org/docs/intro/install"; exit 1; }

if [[ ! -f "$TFVARS_FILE" ]]; then
  echo "ERROR: tfvars file not found: $TFVARS_FILE"
  exit 1
fi

# Verify AWS credentials
echo "Verifying AWS credentials..."
aws sts get-caller-identity > /dev/null || { echo "ERROR: AWS credentials not configured"; exit 1; }

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION=$(aws configure get region || echo "us-east-1")
echo "Account: $ACCOUNT_ID"
echo "Region:  $REGION"
echo ""

# Initialize
cd "$TOFU_DIR"
echo "Initializing OpenTofu..."
tofu init -input=false \
  -backend-config="bucket=${MASON_TF_STATE_BUCKET:-giftbee-tofu-state}" \
  -backend-config="dynamodb_table=${MASON_TF_LOCK_TABLE:-giftbee-tofu-locks}"

# Plan or apply
case "$ACTION" in
  plan)
    echo "Planning..."
    tofu plan -var-file="$TFVARS_FILE" -out=tfplan
    echo ""
    echo "Review the plan above. To apply: ./scripts/deploy.sh $ENVIRONMENT apply"
    ;;
  apply)
    echo "Planning..."
    tofu plan -var-file="$TFVARS_FILE" -out=tfplan

    echo ""
    echo "Applying..."
    tofu apply -input=false tfplan

    rm -f tfplan
    ;;
  destroy)
    echo "Destroying..."
    tofu destroy -var-file="$TFVARS_FILE" -auto-approve
    ;;
  *)
    echo "ERROR: Unknown action '$ACTION'. Use: plan, apply, or destroy"
    exit 1
    ;;
esac

echo ""
echo "=== Done ==="

# Show outputs
if [[ "$ACTION" == "apply" ]]; then
  echo ""
  echo "Outputs:"
  tofu output
fi
