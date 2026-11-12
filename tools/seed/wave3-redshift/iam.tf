data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.redshift.amazonaws.com"]
    }
  }
}

# The scheduled action may pause and resume the seed cluster; nothing else. The action is disabled, so it never runs.
data "aws_iam_policy_document" "scheduler" {
  statement {
    actions   = ["redshift:PauseCluster", "redshift:ResumeCluster"]
    resources = [aws_redshift_cluster.seed.arn]
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "seed-w3r-${var.run_id}-scheduler-role"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json

  depends_on = [terraform_data.guard]
}

resource "aws_iam_policy" "scheduler" {
  name   = "seed-w3r-${var.run_id}-scheduler-policy"
  policy = data.aws_iam_policy_document.scheduler.json

  depends_on = [terraform_data.guard]
}

resource "aws_iam_role_policy_attachment" "scheduler" {
  role       = aws_iam_role.scheduler.name
  policy_arn = aws_iam_policy.scheduler.arn
}
