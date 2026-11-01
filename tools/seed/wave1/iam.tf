data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com", "lambda.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "seed" {
  statement {
    actions   = ["sts:GetCallerIdentity"]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "seed" {
  name   = "seed-w1-${var.run_id}-policy"
  policy = data.aws_iam_policy_document.seed.json

  depends_on = [terraform_data.guard]
}

resource "aws_iam_role" "seed" {
  name               = "seed-w1-${var.run_id}-role"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

resource "aws_iam_role_policy_attachment" "seed" {
  role       = aws_iam_role.seed.name
  policy_arn = aws_iam_policy.seed.arn
}

resource "aws_iam_instance_profile" "seed" {
  name = "seed-w1-${var.run_id}-instance-profile"
  role = aws_iam_role.seed.name
}

# Awkward case: tag keys and values with spaces, colons, slashes, unicode letters and an empty value.
resource "aws_iam_user" "seed" {
  name = "seed-w1-${var.run_id}-user"
  tags = {
    "team name"   = "red team: alpha"
    "cost:center" = "naïve café"
    "path/like"   = "a=b+c@d"
    "empty-value" = ""
  }
}

resource "aws_iam_user_policy_attachment" "seed" {
  user       = aws_iam_user.seed.name
  policy_arn = aws_iam_policy.seed.arn
}

# IAM groups cannot carry tags: the collector must report {} and the expected inventory records {}.
resource "aws_iam_group" "seed" {
  name = "seed-w1-${var.run_id}-group"
}

resource "aws_iam_group_policy_attachment" "seed" {
  group      = aws_iam_group.seed.name
  policy_arn = aws_iam_policy.seed.arn
}

resource "aws_iam_group_membership" "seed" {
  name  = "seed-w1-${var.run_id}-membership"
  group = aws_iam_group.seed.name
  users = [aws_iam_user.seed.name]
}
