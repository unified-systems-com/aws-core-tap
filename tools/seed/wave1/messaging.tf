# The queue carries no tag of its own: it has only the two defaults.
resource "aws_sqs_queue" "seed" {
  name = "${local.prefix}-queue"

  depends_on = [terraform_data.guard]
}

resource "aws_sns_topic" "seed" {
  name              = "${local.prefix}-topic"
  kms_master_key_id = aws_kms_key.seed.arn

  depends_on = [terraform_data.guard]
}

data "archive_file" "fn" {
  type        = "zip"
  output_path = "${path.module}/.build/fn.zip"

  source {
    filename = "index.py"
    content  = "def handler(event, context):\n    return {\"seed\": \"wave1\"}\n"
  }
}

# The function is never invoked and the group is destroyed with the wave; one day of retention keeps a stray group cheap.
resource "aws_cloudwatch_log_group" "fn" {
  name              = "/aws/lambda/${local.prefix}-fn"
  retention_in_days = 1 # NOSONAR

  depends_on = [terraform_data.guard]
}

# The function carries no tag of its own beyond the defaults. It is never invoked, so there is nothing to trace.
# nosemgrep: terraform.aws.security.aws-lambda-x-ray-tracing-not-active.aws-lambda-x-ray-tracing-not-active
resource "aws_lambda_function" "seed" {
  function_name    = "${local.prefix}-fn"
  role             = aws_iam_role.seed.arn
  runtime          = "python3.12"
  handler          = "index.handler"
  memory_size      = 128
  timeout          = 3
  filename         = data.archive_file.fn.output_path
  source_code_hash = data.archive_file.fn.output_base64sha256

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.fn.name
  }

  depends_on = [aws_iam_role_policy_attachment.seed]
}

# Disabled and scheduled: it never fires, so it costs nothing and invokes nothing.
resource "aws_cloudwatch_event_rule" "seed" {
  name                = "${local.prefix}-rule"
  schedule_expression = "rate(1 day)"
  state               = "DISABLED"

  depends_on = [terraform_data.guard]
}

resource "aws_cloudwatch_event_target" "seed" {
  rule      = aws_cloudwatch_event_rule.seed.name
  target_id = "seed-w1-lambda"
  arn       = aws_lambda_function.seed.arn
}
