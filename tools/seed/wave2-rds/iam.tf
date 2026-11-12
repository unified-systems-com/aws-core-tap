data "aws_iam_policy_document" "proxy_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["rds.amazonaws.com"]
    }
  }
}

# The proxy reads the instance's master user secret; nothing else.
data "aws_iam_policy_document" "proxy_secret" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_db_instance.seed.master_user_secret[0].secret_arn]
  }
}

resource "aws_iam_role" "proxy" {
  name               = "seed-w2r-${var.run_id}-proxy-role"
  assume_role_policy = data.aws_iam_policy_document.proxy_assume.json

  depends_on = [terraform_data.guard]
}

resource "aws_iam_policy" "proxy" {
  name   = "seed-w2r-${var.run_id}-proxy-policy"
  policy = data.aws_iam_policy_document.proxy_secret.json

  depends_on = [terraform_data.guard]
}

resource "aws_iam_role_policy_attachment" "proxy" {
  role       = aws_iam_role.proxy.name
  policy_arn = aws_iam_policy.proxy.arn
}
