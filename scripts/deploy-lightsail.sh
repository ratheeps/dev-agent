#!/usr/bin/env bash
# Deploy Mason to a Lightsail instance via rsync + Docker Compose.
#
# Usage:
#   ./scripts/deploy-lightsail.sh                    # deploy to instance
#   ./scripts/deploy-lightsail.sh setup              # first-time infra setup
#   ./scripts/deploy-lightsail.sh logs               # tail container logs
#   ./scripts/deploy-lightsail.sh ssh                # open SSH session
#   ./scripts/deploy-lightsail.sh status             # check container status
#
# Prerequisites:
#   - SSH key for the Lightsail instance (~/.ssh/mason-lightsail.pem)
#   - .env file with all required environment variables
#   - For 'setup': AWS CLI + OpenTofu installed

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ACTION="${1:-deploy}"

# Configuration — override with environment variables if needed
LIGHTSAIL_USER="${LIGHTSAIL_USER:-ec2-user}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/mason-lightsail.pem}"
REMOTE_DIR="/opt/mason"

# Get the instance IP from OpenTofu state or environment
get_instance_ip() {
  if [[ -n "${LIGHTSAIL_IP:-}" ]]; then
    echo "$LIGHTSAIL_IP"
    return
  fi

  local tofu_dir="$PROJECT_ROOT/infra/lightsail"
  if [[ -f "$tofu_dir/terraform.tfstate" ]] || [[ -d "$tofu_dir/.terraform" ]]; then
    cd "$tofu_dir"
    tofu output -raw static_ip 2>/dev/null && return
  fi

  echo "ERROR: Set LIGHTSAIL_IP or run 'setup' first to create infrastructure" >&2
  exit 1
}

ssh_cmd() {
  ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$LIGHTSAIL_USER@$(get_instance_ip)" "$@"
}

case "$ACTION" in
  setup)
    echo "=== Mason Lightsail Infrastructure Setup ==="

    # Verify prerequisites
    command -v aws >/dev/null 2>&1 || { echo "ERROR: aws CLI not found"; exit 1; }
    command -v tofu >/dev/null 2>&1 || { echo "ERROR: tofu not found"; exit 1; }

    echo "Verifying AWS credentials..."
    aws sts get-caller-identity > /dev/null || { echo "ERROR: AWS credentials not configured"; exit 1; }

    # Check if SSH key exists in Lightsail
    KEY_NAME="mason-lightsail"
    if ! aws lightsail get-key-pair --key-pair-name "$KEY_NAME" > /dev/null 2>&1; then
      echo "Creating Lightsail SSH key pair..."
      if [[ -f "$SSH_KEY" ]]; then
        echo "Importing existing key from $SSH_KEY"
        PUBLIC_KEY=$(ssh-keygen -y -f "$SSH_KEY")
        aws lightsail import-key-pair --key-pair-name "$KEY_NAME" --public-key-base64 "$(echo "$PUBLIC_KEY" | base64 -w0)"
      else
        echo "Generating new SSH key pair..."
        RESULT=$(aws lightsail create-key-pair --key-pair-name "$KEY_NAME" --query 'privateKeyBase64' --output text)
        echo "$RESULT" | base64 -d > "$SSH_KEY"
        chmod 600 "$SSH_KEY"
        echo "SSH key saved to $SSH_KEY"
      fi
    fi

    # Run OpenTofu
    cd "$PROJECT_ROOT/infra/lightsail"
    echo "Initializing OpenTofu..."
    tofu init -input=false \
      -backend-config="bucket=${MASON_TF_STATE_BUCKET:-giftbee-tofu-state}" \
      -backend-config="dynamodb_table=${MASON_TF_LOCK_TABLE:-giftbee-tofu-locks}"

    echo "Planning..."
    tofu plan -var-file=terraform.tfvars -out=tfplan

    echo ""
    read -rp "Apply? (y/N) " confirm
    if [[ "$confirm" == "y" || "$confirm" == "Y" ]]; then
      tofu apply -input=false tfplan
      rm -f tfplan
      echo ""
      echo "Infrastructure created. Outputs:"
      tofu output
      echo ""
      echo "Wait ~2 minutes for instance cloud-init, then run:"
      echo "  ./scripts/deploy-lightsail.sh deploy"
    fi
    ;;

  deploy)
    IP=$(get_instance_ip)
    echo "=== Mason Deploy to Lightsail ==="
    echo "Instance: $IP"
    echo ""

    # Verify .env exists
    if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
      echo "ERROR: .env file not found. Copy .env.example and fill in values."
      exit 1
    fi

    # Sync project files to the instance
    echo "Syncing project files..."
    rsync -avz --delete \
      --exclude '.venv/' \
      --exclude '__pycache__/' \
      --exclude '.pytest_cache/' \
      --exclude '.mypy_cache/' \
      --exclude '.ruff_cache/' \
      --exclude '.git/' \
      --exclude 'infra/' \
      --exclude 'docs/' \
      --exclude 'tests/' \
      --exclude '*.pyc' \
      -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=no" \
      "$PROJECT_ROOT/" \
      "$LIGHTSAIL_USER@$IP:$REMOTE_DIR/"

    # Copy .env (excluded from rsync for safety)
    echo "Copying .env..."
    scp -i "$SSH_KEY" -o StrictHostKeyChecking=no \
      "$PROJECT_ROOT/.env" \
      "$LIGHTSAIL_USER@$IP:$REMOTE_DIR/.env"

    # Build and start containers
    echo "Building and starting containers..."
    ssh_cmd "cd $REMOTE_DIR && docker compose -f docker-compose.prod.yml build"
    ssh_cmd "cd $REMOTE_DIR && docker compose -f docker-compose.prod.yml up -d"

    echo ""
    echo "Deployment complete."
    echo "Webhook: http://$IP:8000/health"
    echo "Logs:    ./scripts/deploy-lightsail.sh logs"
    ;;

  logs)
    echo "=== Mason Container Logs ==="
    ssh_cmd "cd $REMOTE_DIR && docker compose -f docker-compose.prod.yml logs -f --tail=100"
    ;;

  ssh)
    echo "Connecting to $(get_instance_ip)..."
    ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$LIGHTSAIL_USER@$(get_instance_ip)"
    ;;

  status)
    echo "=== Mason Container Status ==="
    ssh_cmd "cd $REMOTE_DIR && docker compose -f docker-compose.prod.yml ps"
    echo ""
    echo "=== Health Check ==="
    IP=$(get_instance_ip)
    curl -s "http://$IP:8000/health" 2>/dev/null || echo "Webhook not reachable"
    ;;

  restart)
    echo "Restarting containers..."
    ssh_cmd "cd $REMOTE_DIR && docker compose -f docker-compose.prod.yml restart"
    ;;

  stop)
    echo "Stopping containers..."
    ssh_cmd "cd $REMOTE_DIR && docker compose -f docker-compose.prod.yml down"
    ;;

  destroy)
    echo "=== Destroying Mason Lightsail Infrastructure ==="
    cd "$PROJECT_ROOT/infra/lightsail"
    tofu init -input=false \
      -backend-config="bucket=${MASON_TF_STATE_BUCKET:-giftbee-tofu-state}" \
      -backend-config="dynamodb_table=${MASON_TF_LOCK_TABLE:-giftbee-tofu-locks}"
    tofu destroy -var-file=terraform.tfvars
    ;;

  *)
    echo "Usage: $0 {setup|deploy|logs|ssh|status|restart|stop|destroy}"
    exit 1
    ;;
esac
