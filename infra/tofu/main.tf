provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      project     = var.project
      environment = var.environment
      managed_by  = "opentofu"
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# -----------------------------------------------------
# Networking
# -----------------------------------------------------

module "networking" {
  source = "./modules/networking"

  project     = var.project
  environment = var.environment
  aws_region  = var.aws_region
  vpc_cidr    = var.vpc_cidr
}

# -----------------------------------------------------
# ECR Repositories
# -----------------------------------------------------

module "ecr" {
  source = "./modules/ecr"

  project     = var.project
  environment = var.environment
}

# -----------------------------------------------------
# Task Queue
# -----------------------------------------------------

module "queue" {
  source = "./modules/queue"

  project     = var.project
  environment = var.environment
}

# -----------------------------------------------------
# Memory (DynamoDB)
# -----------------------------------------------------

module "memory" {
  source = "./modules/memory"

  project     = var.project
  environment = var.environment
  kms_key_arn = module.security.kms_key_arn
}

# -----------------------------------------------------
# Gateway (ALB + ACM cert)
# -----------------------------------------------------

module "gateway" {
  source = "./modules/gateway"

  project               = var.project
  environment           = var.environment
  vpc_id                = module.networking.vpc_id
  public_subnet_ids     = module.networking.public_subnet_ids
  alb_security_group_id = module.networking.alb_security_group_id
  domain_name           = var.domain_name
  hosted_zone_id        = var.hosted_zone_id
}

# -----------------------------------------------------
# DNS (Route53 alias — optional)
# -----------------------------------------------------

module "dns" {
  source = "./modules/dns"

  project        = var.project
  environment    = var.environment
  domain_name    = var.domain_name
  hosted_zone_id = var.hosted_zone_id
  alb_dns_name   = module.gateway.alb_dns_name
  alb_zone_id    = module.gateway.alb_zone_id
}

# -----------------------------------------------------
# Runtime (ECS Fargate)
# -----------------------------------------------------

module "runtime" {
  source = "./modules/runtime"

  project               = var.project
  environment           = var.environment
  aws_region            = var.aws_region
  webhook_image         = module.ecr.webhook_repository_url
  worker_image          = module.ecr.worker_repository_url
  webhook_desired_count = var.webhook_desired_count
  worker_cpu            = var.worker_cpu
  worker_memory         = var.worker_memory
  private_subnet_ids    = module.networking.private_subnet_ids
  webhook_security_group_id = module.networking.webhook_ecs_security_group_id
  worker_security_group_id  = module.networking.worker_ecs_security_group_id
  target_group_arn      = module.gateway.target_group_arn
  queue_url             = module.queue.queue_url
  queue_arn             = module.queue.queue_arn
  queue_name            = module.queue.queue_name
}

# -----------------------------------------------------
# Security (WAF, KMS, Secrets)
# -----------------------------------------------------

module "security" {
  source = "./modules/security"

  project     = var.project
  environment = var.environment
  alb_arn     = module.gateway.alb_arn
}

# -----------------------------------------------------
# Observability (Dashboard, Alarms)
# -----------------------------------------------------

module "observability" {
  source = "./modules/observability"

  project                    = var.project
  environment                = var.environment
  daily_cost_alarm_threshold = var.daily_cost_alarm_threshold
  alert_email                = var.alert_email
  memory_table_names         = module.memory.table_names
  ecs_cluster_name           = module.runtime.ecs_cluster_name
  webhook_service_name       = module.runtime.webhook_service_name
  worker_service_name        = module.runtime.worker_service_name
  queue_name                 = module.queue.queue_name
  dlq_name                   = module.queue.dlq_name
  alb_arn_suffix             = regex("app/.*", module.gateway.alb_arn)
  target_group_arn_suffix    = regex("targetgroup/.*", module.gateway.target_group_arn)
}

# -----------------------------------------------------
# CI/CD (GitHub Actions OIDC)
# -----------------------------------------------------

module "cicd" {
  source = "./modules/cicd"

  project              = var.project
  environment          = var.environment
  github_repo          = var.github_repo
  ecr_repository_arns  = [module.ecr.webhook_repository_arn, module.ecr.worker_repository_arn]
  ecs_role_arns = [
    module.runtime.orchestrator_role_arn,
    module.runtime.worker_role_arn,
  ]
  state_bucket = var.state_bucket
  lock_table   = var.lock_table
}
