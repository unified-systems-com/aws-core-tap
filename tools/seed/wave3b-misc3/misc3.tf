# Wave 3b, more definitions that cost nothing while idle: a CloudWatch RUM app monitor, an Amazon Lex V2 bot (no locale, never built) and
# an EventBridge Scheduler schedule that is disabled and aimed at an empty queue. Nothing runs, builds or sends.

# --- CloudWatch RUM ---

resource "aws_rum_app_monitor" "seed" {
  name   = "${local.prefix}-rum"
  domain = "rum.${local.prefix}.example.invalid"

  depends_on = [terraform_data.guard]
}

# --- Amazon Lex V2 bot: the role trusts the service and carries no permission ---

data "aws_iam_policy_document" "lex_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lexv2.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "lex" {
  name               = "seed-w3u-${var.run_id}-lex-role"
  assume_role_policy = data.aws_iam_policy_document.lex_assume.json

  depends_on = [terraform_data.guard]
}

resource "aws_lexv2models_bot" "seed" {
  name                        = "${local.prefix}-bot"
  role_arn                    = aws_iam_role.lex.arn
  idle_session_ttl_in_seconds = 300

  data_privacy {
    child_directed = false
  }

  depends_on = [terraform_data.guard]
}

# --- EventBridge Scheduler: a disabled schedule that points at an empty queue ---

resource "aws_sqs_queue" "seed" {
  name                    = "${local.prefix}-queue"
  sqs_managed_sse_enabled = true

  depends_on = [terraform_data.guard]
}

data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "seed-w3u-${var.run_id}-scheduler-role"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json

  depends_on = [terraform_data.guard]
}

resource "aws_iam_role_policy" "scheduler" {
  name = "${local.prefix}-send"
  role = aws_iam_role.scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["sqs:SendMessage"]
      Resource = [aws_sqs_queue.seed.arn]
    }]
  })
}

resource "aws_scheduler_schedule" "seed" {
  name                = "${local.prefix}-schedule"
  state               = "DISABLED"
  schedule_expression = "rate(1 days)"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_sqs_queue.seed.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ seed = true })
  }

  depends_on = [aws_iam_role_policy.scheduler]
}
