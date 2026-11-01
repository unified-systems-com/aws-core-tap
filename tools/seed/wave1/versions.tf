terraform {
  required_version = ">= 1.6.0"

  # Local state, one file per run: `terraform init -backend-config="path=<run dir>/terraform.tfstate"` (see ../README.md).
  # The state is the expected inventory and the destroy allowlist; it is never committed.
  backend "local" {}

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "= 6.71.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "= 2.7.0"
    }
  }
}
