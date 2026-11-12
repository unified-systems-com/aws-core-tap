data "aws_iam_policy_document" "backup_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["backup.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "grants_assume" {
  statement {
    actions = ["sts:AssumeRole", "sts:SetSourceIdentity", "sts:SetContext"]
    principals {
      type        = "Service"
      identifiers = ["access-grants.s3.amazonaws.com"]
    }
  }
}

# One policy that grants nothing but the caller's identity, as in wave 1.
data "aws_iam_policy_document" "identity_only" {
  statement {
    actions   = ["sts:GetCallerIdentity"]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "identity_only" {
  name   = "seed-w1b-${var.run_id}-policy"
  policy = data.aws_iam_policy_document.identity_only.json

  depends_on = [terraform_data.guard]
}

data "aws_iam_policy_document" "backup_tags" {
  statement {
    actions   = ["tag:GetResources"]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "backup_tags" {
  name   = "seed-w1b-${var.run_id}-backup-policy"
  policy = data.aws_iam_policy_document.backup_tags.json

  depends_on = [terraform_data.guard]
}

resource "aws_iam_role" "backup" {
  name               = "seed-w1b-${var.run_id}-backup-role"
  assume_role_policy = data.aws_iam_policy_document.backup_assume.json

  depends_on = [terraform_data.guard]
}

resource "aws_iam_role_policy_attachment" "backup" {
  role       = aws_iam_role.backup.name
  policy_arn = aws_iam_policy.backup_tags.arn
}

resource "aws_iam_role" "grants" {
  name               = "seed-w1b-${var.run_id}-grants-role"
  assume_role_policy = data.aws_iam_policy_document.grants_assume.json

  depends_on = [terraform_data.guard]
}

resource "aws_iam_role_policy_attachment" "grants" {
  role       = aws_iam_role.grants.name
  policy_arn = aws_iam_policy.identity_only.arn
}
