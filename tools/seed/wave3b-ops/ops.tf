# Wave 3b, operations: CloudWatch Logs, CloudWatch, EventBridge, Systems Manager, SNS, CloudFormation, Auto Scaling and
# ECR. Everything here is free while idle: nothing is invoked, nothing is ingested, no instance is launched.

data "aws_availability_zones" "available" {
  state = "available"
}

# --- SNS: a topic and a subscription from a queue in the same account (confirmed without a message) ---

resource "aws_sqs_queue" "sink" {
  name = "${local.prefix}-sink"

  depends_on = [terraform_data.guard]
}

# Left unencrypted on purpose: it holds no message, and a key of the module's own would add a costed resource, while the
# AWS managed alias would be an edge target the catalog cannot resolve.
resource "aws_sns_topic" "seed" { # NOSONAR: empty, run-scoped and destroyed within the hour; no message is ever published
  name = "${local.prefix}-topic"

  depends_on = [terraform_data.guard]
}

resource "aws_sns_topic_subscription" "seed" {
  topic_arn = aws_sns_topic.seed.arn
  protocol  = "sqs"
  endpoint  = aws_sqs_queue.sink.arn
}

# --- CloudWatch Logs ---

resource "aws_cloudwatch_log_group" "seed" {
  name              = "/seed/${local.prefix}"
  retention_in_days = 1 # NOSONAR

  depends_on = [terraform_data.guard]
}

resource "aws_cloudwatch_log_metric_filter" "seed" {
  name           = "${local.prefix}-filter"
  pattern        = "ERROR"
  log_group_name = aws_cloudwatch_log_group.seed.name

  metric_transformation {
    name      = "${local.prefix}-errors"
    namespace = "seed/${local.prefix}"
    value     = "1"
  }
}

resource "aws_cloudwatch_query_definition" "seed" {
  name            = "${local.prefix}-query"
  query_string    = "fields @timestamp, @message | limit 20"
  log_group_names = [aws_cloudwatch_log_group.seed.name]
}

# --- CloudWatch ---

resource "aws_cloudwatch_metric_alarm" "seed" {
  alarm_name          = "${local.prefix}-alarm"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Average"
  threshold           = 100
  actions_enabled     = false

  dimensions = {
    QueueName = aws_sqs_queue.sink.name
  }
}

resource "aws_cloudwatch_composite_alarm" "seed" {
  alarm_name      = "${local.prefix}-composite"
  alarm_rule      = "ALARM(${aws_cloudwatch_metric_alarm.seed.alarm_name})"
  actions_enabled = false
}

resource "aws_cloudwatch_dashboard" "seed" {
  dashboard_name = "${local.prefix}-dashboard"
  dashboard_body = jsonencode({ widgets = [] })
}

# --- EventBridge ---

resource "aws_cloudwatch_event_bus" "seed" {
  name = "${local.prefix}-bus"

  depends_on = [terraform_data.guard]
}

resource "aws_cloudwatch_event_archive" "seed" {
  name             = "${local.prefix}-archive"
  event_source_arn = aws_cloudwatch_event_bus.seed.arn
  retention_days   = 1
}

# --- Systems Manager ---

resource "aws_ssm_document" "seed" {
  name            = "${local.prefix}-document"
  document_type   = "Command"
  document_format = "JSON"

  content = jsonencode({
    schemaVersion = "2.2"
    description   = "seed document that runs nothing"
    mainSteps = [{
      action = "aws:runShellScript"
      name   = "noop"
      inputs = { runCommand = ["true"] }
    }]
  })

  depends_on = [terraform_data.guard]
}

resource "aws_ssm_maintenance_window" "seed" {
  name     = "${local.prefix}-window"
  schedule = "cron(0 0 ? * SUN *)"
  duration = 2
  cutoff   = 1
  enabled  = false
}

resource "aws_ssm_patch_baseline" "seed" {
  name             = "${local.prefix}-baseline"
  operating_system = "AMAZON_LINUX_2023"

  approval_rule {
    approve_after_days = 7

    patch_filter {
      key    = "CLASSIFICATION"
      values = ["Security"]
    }
  }
}

# Targets a tag value that names this run, so no instance can carry it and the association never runs.
resource "aws_ssm_association" "seed" {
  name             = aws_ssm_document.seed.name
  association_name = "${local.prefix}-association"

  targets {
    key    = "tag:seed-no-such-tag"
    values = ["none-${var.run_id}"]
  }
}

# --- CloudFormation: a stack whose one resource is a wait condition handle, which has no cost and no side effect ---

resource "aws_cloudformation_stack" "seed" {
  name = "${local.prefix}-stack"

  template_body = jsonencode({
    AWSTemplateFormatVersion = "2010-09-09"
    Resources = {
      Handle = { Type = "AWS::CloudFormation::WaitConditionHandle" }
    }
  })

  depends_on = [terraform_data.guard]
}

# --- Auto Scaling: a group that is never given an instance (minimum, desired and maximum are all 0) ---

data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-kernel-*-x86_64"]
  }
  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
  filter {
    name   = "root-device-type"
    values = ["ebs"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

resource "aws_vpc" "seed" {
  cidr_block = "10.93.0.0/16"

  depends_on = [terraform_data.guard]
}

resource "aws_subnet" "a" {
  vpc_id            = aws_vpc.seed.id
  cidr_block        = "10.93.1.0/24"
  availability_zone = data.aws_availability_zones.available.names[0]
}

resource "aws_launch_template" "seed" {
  name          = "${local.prefix}-template"
  image_id      = data.aws_ami.al2023.id
  instance_type = "t3.micro"

  metadata_options {
    http_tokens = "required"
  }

  network_interfaces {
    associate_public_ip_address = false
  }

  depends_on = [terraform_data.guard]
}

resource "aws_autoscaling_group" "seed" {
  name                 = "${local.prefix}-asg"
  min_size             = 0
  max_size             = 0
  desired_capacity     = 0
  vpc_zone_identifier  = [aws_subnet.a.id]

  launch_template {
    id      = aws_launch_template.seed.id
    version = "$Latest"
  }
}

resource "aws_autoscaling_policy" "seed" {
  name                   = "${local.prefix}-scale"
  autoscaling_group_name = aws_autoscaling_group.seed.name
  adjustment_type        = "ChangeInCapacity"
  scaling_adjustment     = 1
  cooldown               = 300
}

resource "aws_autoscaling_schedule" "seed" {
  scheduled_action_name  = "${local.prefix}-schedule"
  autoscaling_group_name = aws_autoscaling_group.seed.name
  min_size               = 0
  max_size               = 0
  desired_capacity       = 0
  recurrence             = "0 0 1 1 *"
}

# --- ECR ---

resource "aws_ecr_repository" "seed" {
  name                 = "${local.prefix}-repo"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  depends_on = [terraform_data.guard]
}
