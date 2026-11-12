# Wave 3b, small account-level definitions that cost nothing while idle: an EventBridge Scheduler group, an X-Ray group and sampling
# rule, a Resource Groups group, a Signer signing profile, a CodeCommit repository, a Resource Access Manager share with nothing shared,
# a CloudWatch Synthetics group, a CodeConnections connection (left pending, never authorised) and a Recycle Bin rule. Nothing is
# invoked, signed, shared or retained.

locals {
  # Signer profile names allow letters, digits and underscores only.
  prefix_us = replace(local.prefix, "-", "_")
}

resource "aws_scheduler_schedule_group" "seed" {
  name = "${local.prefix}-group"

  depends_on = [terraform_data.guard]
}

resource "aws_xray_group" "seed" {
  group_name        = "${local.prefix}-xray"
  filter_expression = "responsetime > 5"

  depends_on = [terraform_data.guard]
}

resource "aws_xray_sampling_rule" "seed" {
  rule_name      = "${local.prefix}-rule"
  priority       = 9000
  version        = 1
  reservoir_size = 1
  fixed_rate     = 0.05
  url_path       = "*"
  host           = "*"
  http_method    = "*"
  service_type   = "*"
  service_name   = "seed"
  resource_arn   = "*"

  depends_on = [terraform_data.guard]
}

resource "aws_resourcegroups_group" "seed" {
  name = "${local.prefix}-rg"

  resource_query {
    type = "TAG_FILTERS_1_0"
    query = jsonencode({
      ResourceTypeFilters = ["AWS::AllSupported"]
      TagFilters          = [{ Key = "tap-seed-run", Values = [var.run_id] }]
    })
  }

  depends_on = [terraform_data.guard]
}

resource "aws_signer_signing_profile" "seed" {
  name        = "${local.prefix_us}_profile"
  platform_id = "AWSLambda-SHA384-ECDSA"

  depends_on = [terraform_data.guard]
}

resource "aws_codecommit_repository" "seed" {
  repository_name = "${local.prefix}-repo"

  depends_on = [terraform_data.guard]
}

resource "aws_ram_resource_share" "seed" {
  name                      = "${local.prefix}-share"
  allow_external_principals = false

  depends_on = [terraform_data.guard]
}

resource "aws_synthetics_group" "seed" {
  name = "${local.prefix}-synth"

  depends_on = [terraform_data.guard]
}

resource "aws_codestarconnections_connection" "seed" {
  name          = "${local.prefix}-conn"
  provider_type = "GitHub"

  depends_on = [terraform_data.guard]
}

resource "aws_rbin_rule" "seed" {
  description   = "${local.prefix} rule"
  resource_type = "EBS_SNAPSHOT"

  resource_tags {
    resource_tag_key   = "tap-seed-retain"
    resource_tag_value = var.run_id
  }

  retention_period {
    retention_period_value = 1
    retention_period_unit  = "DAYS"
  }

  depends_on = [terraform_data.guard]
}
