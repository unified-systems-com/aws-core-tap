# Wave 3b, transfer definitions: an AWS Transfer Family SFTP server on a VPC endpoint with a user and a workflow, a Pinpoint app and
# an AppStream stack. The one hourly charge is the Transfer server; the cost note prices it. Nothing is connected: no file is
# transferred, no message is sent and no stream starts.

data "aws_availability_zones" "available" {
  state = "available"
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

# One group with no rules at all.
resource "aws_security_group" "seed" {
  name        = "${local.prefix}-sg"
  description = "seed wave 3b xfer: no rules"
  vpc_id      = aws_vpc.seed.id
}

# --- Transfer Family ---

data "aws_iam_policy_document" "transfer_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["transfer.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

# A role with no permissions: the user only records it, and nobody can sign in.
resource "aws_iam_role" "transfer" {
  name               = "seed-w3t-${var.run_id}-transfer-role"
  assume_role_policy = data.aws_iam_policy_document.transfer_assume.json

  depends_on = [terraform_data.guard]
}

resource "aws_transfer_server" "seed" {
  endpoint_type          = "VPC"
  protocols              = ["SFTP"]
  identity_provider_type = "SERVICE_MANAGED"

  endpoint_details {
    vpc_id             = aws_vpc.seed.id
    subnet_ids         = [aws_subnet.a.id]
    security_group_ids = [aws_security_group.seed.id]
  }

  depends_on = [terraform_data.guard]
}

resource "aws_transfer_user" "seed" {
  server_id = aws_transfer_server.seed.id
  user_name = "seed${var.run_id}"
  role      = aws_iam_role.transfer.arn
}

resource "aws_transfer_workflow" "seed" {
  description = "${local.prefix} workflow"

  steps {
    type = "DELETE"

    delete_step_details {
      name                 = "delete"
      source_file_location = "$${original.file}"
    }
  }

  depends_on = [terraform_data.guard]
}

# --- Pinpoint and AppStream ---

resource "aws_pinpoint_app" "seed" {
  name = "${local.prefix}-app"

  depends_on = [terraform_data.guard]
}

resource "aws_appstream_stack" "seed" {
  name = "${local.prefix}-stack"

  depends_on = [terraform_data.guard]
}
