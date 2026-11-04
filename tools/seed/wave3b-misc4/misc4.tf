# Wave 3b, two more definitions that cost nothing while idle: a published Amazon Bedrock guardrail version (a numbered copy of a guardrail
# with one blocked word) and a CloudWatch alarm mute rule over a metric alarm that has no data. Nothing is invoked, evaluated or muted
# in effect: the alarm watches a metric nothing publishes, and the rule mutes one hour a year.

resource "aws_bedrock_guardrail" "seed" {
  name                      = "${local.prefix}-guardrail"
  blocked_input_messaging   = "blocked"
  blocked_outputs_messaging = "blocked"

  word_policy_config {
    words_config {
      text = "seedword"
    }
  }

  depends_on = [terraform_data.guard]
}

resource "aws_bedrock_guardrail_version" "seed" {
  guardrail_arn = aws_bedrock_guardrail.seed.guardrail_arn
  description   = "${local.prefix} version"
}

resource "aws_cloudwatch_metric_alarm" "seed" {
  alarm_name          = "${local.prefix}-alarm"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "SeedMetric${var.run_id}"
  namespace           = "SeedW3i${var.run_id}"
  period              = 300
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"

  depends_on = [terraform_data.guard]
}

resource "aws_cloudwatch_alarm_mute_rule" "seed" {
  name        = "${local.prefix}-mute"
  description = "${local.prefix} mute rule"

  mute_targets {
    alarm_names = [aws_cloudwatch_metric_alarm.seed.alarm_name]
  }

  rule {
    schedule {
      expression = "cron(0 3 1 1 *)"
      duration   = "PT1H"
      timezone   = "UTC"
    }
  }
}
