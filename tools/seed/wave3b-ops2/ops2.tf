# Wave 3b, more operations definitions, among them the types whose key the collector builds from the account and region: an ECR
# repository creation template, an Auto Scaling lifecycle hook (on a group of capacity zero) and a CloudWatch
# Contributor Insights rule. Nothing launches: the group holds no instance and the rule reads a log group nothing writes to.

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "seed" {
  cidr_block = "10.91.0.0/16"

  depends_on = [terraform_data.guard]
}

resource "aws_subnet" "a" {
  vpc_id            = aws_vpc.seed.id
  cidr_block        = "10.91.1.0/24"
  availability_zone = data.aws_availability_zones.available.names[0]
}

# --- ECR repository creation template ---

resource "aws_ecr_repository_creation_template" "seed" {
  prefix      = "seed-w3q-${var.run_id}"
  applied_for = ["REPLICATION"]
  description = "${local.prefix} template"

  image_tag_mutability = "IMMUTABLE"

  encryption_configuration {
    encryption_type = "AES256"
  }

  depends_on = [terraform_data.guard]
}

# --- Auto Scaling: a group that never holds an instance, and a lifecycle hook on it ---

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
  name                = "${local.prefix}-asg"
  min_size            = 0
  max_size            = 0
  desired_capacity    = 0
  vpc_zone_identifier = [aws_subnet.a.id]

  launch_template {
    id      = aws_launch_template.seed.id
    version = "$Latest"
  }
}

resource "aws_autoscaling_lifecycle_hook" "seed" {
  name                   = "${local.prefix}-hook"
  autoscaling_group_name = aws_autoscaling_group.seed.name
  lifecycle_transition   = "autoscaling:EC2_INSTANCE_LAUNCHING"
  heartbeat_timeout      = 300
  default_result         = "CONTINUE"
}

# --- Contributor Insights: a rule over a log group nothing writes to ---

resource "aws_cloudwatch_log_group" "seed" {
  name              = "/seed/${local.prefix}-insight"
  retention_in_days = 1 # NOSONAR

  depends_on = [terraform_data.guard]
}

resource "aws_cloudwatch_contributor_insight_rule" "seed" {
  rule_name = "${local.prefix}-insight"

  rule_definition = jsonencode({
    Schema        = { Name = "CloudWatchLogRule", Version = 1 }
    LogGroupNames = [aws_cloudwatch_log_group.seed.name]
    LogFormat     = "JSON"
    Contribution = {
      Keys    = ["$.ip"]
      Filters = []
    }
    AggregateOn = "Count"
  })
}
