# Wave 3b, more compute definitions: a Lambda code signing configuration (and the Signer profile it names), an external-deployment ECS
# service with a task set of scale zero, and a Data Lifecycle Manager policy left disabled. Nothing is invoked, signed, launched or run:
# the task set starts no task and the policy is off.

locals {
  # Signer profile names allow letters, digits and underscores only.
  prefix_us = replace(local.prefix, "-", "_")
}

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "seed" {
  cidr_block = "10.90.0.0/16"

  depends_on = [terraform_data.guard]
}

resource "aws_subnet" "a" {
  vpc_id            = aws_vpc.seed.id
  cidr_block        = "10.90.1.0/24"
  availability_zone = data.aws_availability_zones.available.names[0]
}

# One group with no rules at all.
resource "aws_security_group" "seed" {
  name        = "${local.prefix}-sg"
  description = "seed wave 3b compute2: no rules"
  vpc_id      = aws_vpc.seed.id
}

# --- Lambda: a code signing configuration, and the Signer profile it names ---

resource "aws_signer_signing_profile" "seed" {
  name        = "${local.prefix_us}_profile"
  platform_id = "AWSLambda-SHA384-ECDSA"

  depends_on = [terraform_data.guard]
}

resource "aws_lambda_code_signing_config" "seed" {
  description = "${local.prefix} signing"

  allowed_publishers {
    signing_profile_version_arns = [aws_signer_signing_profile.seed.version_arn]
  }

  policies {
    untrusted_artifact_on_deployment = "Warn"
  }
}

# --- ECS: an external-deployment service with a task set of scale zero ---


resource "aws_ecs_cluster" "seed" {
  name = "${local.prefix}-cluster"

  depends_on = [terraform_data.guard]
}

resource "aws_ecs_task_definition" "seed" {
  family                   = "${local.prefix}-task"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512

  container_definitions = jsonencode([{
    name      = "seed"
    image     = "public.ecr.aws/docker/library/busybox:latest"
    essential = true
    command   = ["true"]
  }])
}

resource "aws_ecs_service" "seed" {
  name          = "${local.prefix}-service"
  cluster       = aws_ecs_cluster.seed.arn
  desired_count = 0

  deployment_controller {
    type = "EXTERNAL"
  }
}

resource "aws_ecs_task_set" "seed" {
  cluster         = aws_ecs_cluster.seed.id
  service         = aws_ecs_service.seed.id
  task_definition = aws_ecs_task_definition.seed.arn
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = [aws_subnet.a.id]
    security_groups  = [aws_security_group.seed.id]
    assign_public_ip = false
  }

  scale {
    value = 0
    unit  = "PERCENT"
  }

  force_delete = true
}

# --- Data Lifecycle Manager: a snapshot policy, disabled ---

data "aws_iam_policy_document" "dlm_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["dlm.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

# A role with no permissions: the policy is disabled and never runs.
resource "aws_iam_role" "dlm" {
  name               = "seed-w3j-${var.run_id}-dlm-role"
  assume_role_policy = data.aws_iam_policy_document.dlm_assume.json

  depends_on = [terraform_data.guard]
}

resource "aws_dlm_lifecycle_policy" "seed" {
  description        = "${local.prefix} snapshots"
  execution_role_arn = aws_iam_role.dlm.arn
  state              = "DISABLED"

  policy_details {
    resource_types = ["VOLUME"]

    target_tags = {
      "tap-seed-snapshot" = var.run_id
    }

    schedule {
      name = "daily"

      create_rule {
        interval      = 24
        interval_unit = "HOURS"
        times         = ["03:00"]
      }

      retain_rule {
        count = 1
      }
    }
  }
}
