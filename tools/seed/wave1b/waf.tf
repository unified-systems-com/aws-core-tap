# Regional WAFv2 objects with nothing attached to them. A web ACL is billed by the hour while it exists.
resource "aws_wafv2_ip_set" "seed" {
  name               = "${local.prefix}-ipset"
  scope              = "REGIONAL"
  ip_address_version = "IPV4"
  addresses          = ["192.0.2.0/24"]

  depends_on = [terraform_data.guard]
}

resource "aws_wafv2_regex_pattern_set" "seed" {
  name  = "${local.prefix}-regex"
  scope = "REGIONAL"

  regular_expression {
    regex_string = "^seed-w1b$"
  }

  depends_on = [terraform_data.guard]
}

resource "aws_wafv2_rule_group" "seed" {
  name     = "${local.prefix}-rules"
  scope    = "REGIONAL"
  capacity = 2

  rule {
    name     = "block-the-documentation-range"
    priority = 1

    action {
      block {}
    }

    statement {
      ip_set_reference_statement {
        arn = aws_wafv2_ip_set.seed.arn
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = false
      metric_name                = "seedw1brule"
      sampled_requests_enabled   = false
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = false
    metric_name                = "seedw1bgroup"
    sampled_requests_enabled   = false
  }
}

resource "aws_wafv2_web_acl" "seed" {
  name  = "${local.prefix}-acl"
  scope = "REGIONAL"

  default_action {
    allow {}
  }

  visibility_config {
    cloudwatch_metrics_enabled = false
    metric_name                = "seedw1bacl"
    sampled_requests_enabled   = false
  }

  depends_on = [terraform_data.guard]
}
