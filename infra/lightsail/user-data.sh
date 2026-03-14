#!/bin/bash
# Cloud-init script for Mason Lightsail instance.
# Installs Docker, Docker Compose, and prepares the deployment directory.

set -euo pipefail

# Update system
dnf update -y

# Install Docker
dnf install -y docker git
systemctl enable docker
systemctl start docker

# Install Docker Compose plugin
DOCKER_CONFIG=/usr/local/lib/docker
mkdir -p "$DOCKER_CONFIG/cli-plugins"
curl -SL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-$(uname -m)" \
  -o "$DOCKER_CONFIG/cli-plugins/docker-compose"
chmod +x "$DOCKER_CONFIG/cli-plugins/docker-compose"

# Add ec2-user to docker group
usermod -aG docker ec2-user

# Create deployment directory
mkdir -p /opt/mason
chown ec2-user:ec2-user /opt/mason

# Install AWS CLI v2 (for SQS/DynamoDB access)
curl "https://awscli.amazonaws.com/awscli-exe-linux-$(uname -m).zip" -o /tmp/awscliv2.zip
cd /tmp && unzip -q awscliv2.zip && ./aws/install
rm -rf /tmp/aws /tmp/awscliv2.zip

echo "Mason Lightsail instance setup complete"
