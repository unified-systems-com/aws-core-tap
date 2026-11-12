# A trail that is created switched off: it records nothing and writes nothing.
resource "aws_cloudtrail" "seed" {
  name                          = "${local.prefix}-trail"
  s3_bucket_name                = aws_s3_bucket.trail.id
  enable_logging                = false
  is_multi_region_trail         = false
  include_global_service_events = false
  enable_log_file_validation    = true

  depends_on = [aws_s3_bucket_policy.trail]
}

# Children of the account's existing Security Hub and Config, created and destroyed here; nothing existing is changed.
resource "aws_securityhub_action_target" "seed" {
  identifier  = "seedw1b${substr(var.run_id, 0, 8)}"
  name        = "seed-w1b-${var.run_id}"
  description = "seed wave 1b: custom action"
}

resource "aws_securityhub_insight" "seed" {
  name               = "seed-w1b-${var.run_id}"
  group_by_attribute = "ResourceType"

  filters {
    resource_type {
      comparison = "EQUALS"
      value      = "AwsAccount"
    }
  }
}

resource "aws_config_aggregate_authorization" "seed" {
  account_id            = data.aws_caller_identity.current.account_id
  authorized_aws_region = "us-gov-east-1"
}
