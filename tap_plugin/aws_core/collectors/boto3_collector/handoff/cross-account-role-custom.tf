# TAP AWS Core collector — the same cross-account role as cross-account-role.tf, but with the collector's own
# least-privilege policy (collector-policy-NN.json, generated from what the collector can call) in place of the
# AWS-managed SecurityAudit + ReadOnlyAccess. Use one or the other, not both.
#
#   terraform apply -var 'trustee_principal_arn=arn:aws:iam::<tap-account>:user/<collector>' -var 'external_id=<id>'
#
# The policy documents are customer-managed policies (one per file, each under IAM's 6,144-character limit); a role
# can hold ten by default, and the collector uses the first N files that exist here.

variable "trustee_principal_arn" { type = string }
variable "external_id" {
  type      = string
  sensitive = true
}
variable "role_name" {
  type    = string
  default = "tap-aws-core-collector"
}

locals {
  policy_files = sort(fileset(path.module, "collector-policy-*.json"))
}

resource "aws_iam_policy" "collector" {
  for_each = toset(local.policy_files)
  name     = "${var.role_name}-${trimsuffix(trimprefix(each.key, "collector-policy-"), ".json")}"
  policy   = file("${path.module}/${each.key}")
}

resource "aws_iam_role" "collector" {
  name = var.role_name
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { AWS = var.trustee_principal_arn }
      Condition = { StringEquals = { "sts:ExternalId" = var.external_id } }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "collector" {
  for_each   = aws_iam_policy.collector
  role       = aws_iam_role.collector.name
  policy_arn = each.value.arn
}
