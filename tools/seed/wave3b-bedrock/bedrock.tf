# Wave 3b, Bedrock: definitions only. A guardrail, a prompt, a flow and an application inference profile (new agents cannot be created: Bedrock Agents is in maintenance mode).
# Nothing is invoked, so nothing is billed: no model call is made, and no knowledge base, vector store or provisioned throughput
# is created.

data "aws_iam_policy_document" "bedrock_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "flow" {
  name               = "seed-w3m-${var.run_id}-flow-role"
  assume_role_policy = data.aws_iam_policy_document.bedrock_assume.json

  depends_on = [terraform_data.guard]
}

resource "aws_iam_role_policy" "flow" {
  name = "${local.prefix}-flow-invoke"
  role = aws_iam_role.flow.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["bedrock:InvokeModel"]
      Resource = ["arn:${data.aws_partition.current.partition}:bedrock:${data.aws_region.current.region}::foundation-model/amazon.nova-lite-v1:0"]
    }]
  })
}

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

resource "aws_bedrockagent_prompt" "seed" {
  name            = "${local.prefix}-prompt"
  default_variant = "v1"

  variant {
    name          = "v1"
    model_id      = "amazon.nova-lite-v1:0"
    template_type = "TEXT"

    template_configuration {
      text {
        text = "Say hello."
      }
    }
  }

  depends_on = [terraform_data.guard]
}

resource "aws_bedrockagent_flow" "seed" {
  name               = "${local.prefix}-flow"
  execution_role_arn = aws_iam_role.flow.arn

  definition {
    node {
      name = "in"
      type = "Input"

      configuration {
        input {}
      }

      output {
        name = "document"
        type = "String"
      }
    }

    node {
      name = "out"
      type = "Output"

      configuration {
        output {}
      }

      input {
        name       = "document"
        type       = "String"
        expression = "$.data"
      }
    }

    connection {
      name   = "inToOut"
      source = "in"
      target = "out"
      type   = "Data"

      configuration {
        data {
          source_output = "document"
          target_input  = "document"
        }
      }
    }
  }

  depends_on = [aws_iam_role_policy.flow]
}

resource "aws_bedrock_inference_profile" "seed" {
  name = "${local.prefix}-profile"

  model_source {
    copy_from = "arn:${data.aws_partition.current.partition}:bedrock:${data.aws_region.current.region}::foundation-model/amazon.nova-lite-v1:0"
  }

  depends_on = [terraform_data.guard]
}
