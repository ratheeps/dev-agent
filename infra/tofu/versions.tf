terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    # Real values are passed at init time via -backend-config flags.
    # See scripts/deploy.sh and .github/workflows/deploy.yml.
    bucket         = "placeholder"
    key            = "mason/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "placeholder"
    encrypt        = true
  }
}
