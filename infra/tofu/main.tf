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
# Modules
# -----------------------------------------------------

module "memory" {
  source = "./modules/memory"

  project     = var.project
  environment = var.environment
}

module "runtime" {
  source = "./modules/runtime"

  project     = var.project
  environment = var.environment
  aws_region  = var.aws_region
}

module "gateway" {
  source = "./modules/gateway"

  project     = var.project
  environment = var.environment
}

module "observability" {
  source = "./modules/observability"

  project                    = var.project
  environment                = var.environment
  daily_cost_alarm_threshold = var.daily_cost_alarm_threshold
  alert_email                = var.alert_email
  memory_table_names         = module.memory.table_names
}
