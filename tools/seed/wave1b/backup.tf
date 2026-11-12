resource "aws_backup_vault" "seed" {
  name = "${local.prefix}-vault"

  depends_on = [terraform_data.guard]
}

resource "aws_backup_plan" "seed" {
  name = "${local.prefix}-plan"

  rule {
    rule_name         = "seed-rule"
    target_vault_name = aws_backup_vault.seed.name
    schedule          = "cron(0 5 ? * * *)"
  }
}

# Selects nothing real: a resource tag no resource carries.
resource "aws_backup_selection" "seed" {
  name         = "${local.prefix}-selection"
  plan_id      = aws_backup_plan.seed.id
  iam_role_arn = aws_iam_role.backup.arn

  depends_on = [aws_iam_role_policy_attachment.backup]

  selection_tag {
    type  = "STRINGEQUALS"
    key   = "tap-seed-select"
    value = "none"
  }
}

resource "aws_backup_framework" "seed" {
  name        = "seed_w1b_${var.run_id}_framework"
  description = "seed wave 1b: one control"

  control {
    name = "BACKUP_RECOVERY_POINT_ENCRYPTED"
  }
}

resource "aws_backup_report_plan" "seed" {
  name        = "seed_w1b_${var.run_id}_report"
  description = "seed wave 1b: report plan delivering to an empty bucket"

  report_delivery_channel {
    formats        = ["CSV"]
    s3_bucket_name = aws_s3_bucket.report.id
  }

  report_setting {
    report_template = "BACKUP_JOB_REPORT"
  }
}
