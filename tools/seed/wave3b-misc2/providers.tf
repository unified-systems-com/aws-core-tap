provider "aws" {
  region  = "us-gov-west-1"
  profile = var.profile

  # The provider refuses to plan or apply in any other account.
  allowed_account_ids = [var.expected_account_id]

  default_tags {
    tags = {
      "tap-seed"     = "wave3b-misc2"
      "tap-seed-run" = var.run_id
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_region" "current" {}

locals {
  prefix = "seed-w3z-${var.run_id}"
}

# Fails the plan, before anything is created, unless this is the GovCloud partition and the home region.
resource "terraform_data" "guard" {
  lifecycle {
    precondition {
      condition     = data.aws_partition.current.partition == "aws-us-gov" && data.aws_region.current.region == "us-gov-west-1"
      error_message = "Wave 3b misc2 acts only in partition aws-us-gov, region us-gov-west-1."
    }
  }
}
