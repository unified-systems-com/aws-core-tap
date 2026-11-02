resource "aws_kms_key" "seed" {
  description             = "${local.prefix} key"
  deletion_window_in_days = 7
  enable_key_rotation     = true

  depends_on = [terraform_data.guard]
}

# KMS aliases cannot carry tags: the expected inventory records {}.
resource "aws_kms_alias" "seed" {
  name          = "alias/${local.prefix}-key"
  target_key_id = aws_kms_key.seed.key_id
}

# Bucket A: versioning, default encryption with the seeded key, the public access block, and awkward tags.
# Both buckets are empty, private, and destroyed with the wave: no access-log target and no HTTPS-only policy, because
# each would be one more resource (and one more bucket to log into) that the projection check does not look at.
resource "aws_s3_bucket" "a" { # NOSONAR
  bucket = "${local.prefix}-bucket-a"
  tags = {
    "weird key: 1/2" = "v = 1+2 @ x"
    "team name"      = "blue team"
  }

  depends_on = [terraform_data.guard]
}

resource "aws_s3_bucket_versioning" "a" {
  bucket = aws_s3_bucket.a.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "a" {
  bucket = aws_s3_bucket.a.id
  rule {
    bucket_key_enabled = true
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.seed.arn
    }
  }
}

resource "aws_s3_bucket_public_access_block" "a" {
  bucket                  = aws_s3_bucket.a.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Bucket B: the bucket-level public access block left at its default (none), and no tags beyond the defaults.
resource "aws_s3_bucket" "b" { # NOSONAR
  bucket = "${local.prefix}-bucket-b"

  depends_on = [terraform_data.guard]
}

# Bucket C: the bucket-level public access block set explicitly to off, the negative case for `public_access_blocked`.
# Still private and empty: no ACL, no policy, no objects. Created only so the check can tell blocked from not blocked.
resource "aws_s3_bucket" "c" { # NOSONAR
  bucket = "${local.prefix}-bucket-c"

  depends_on = [terraform_data.guard]
}

resource "aws_s3_bucket_public_access_block" "c" { # NOSONAR
  bucket                  = aws_s3_bucket.c.id
  block_public_acls       = false
  block_public_policy     = false
  ignore_public_acls      = false
  restrict_public_buckets = false
}

# The table is empty and destroyed with the wave. It is encrypted at rest with the AWS-owned key by default; a
# customer-managed key would be a second key for nothing to protect.
# nosemgrep: terraform.aws.security.aws-dynamodb-table-unencrypted.aws-dynamodb-table-unencrypted
resource "aws_dynamodb_table" "seed" {
  name         = "${local.prefix}-table"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"

  attribute {
    name = "id"
    type = "S"
  }

  depends_on = [terraform_data.guard]
}

resource "aws_secretsmanager_secret" "seed" {
  name                    = "${local.prefix}-secret"
  recovery_window_in_days = 0
  kms_key_id              = aws_kms_key.seed.arn

  depends_on = [terraform_data.guard]
}

resource "aws_ssm_parameter" "seed" {
  name  = "/${local.prefix}/param"
  type  = "String"
  value = "seed"
  tier  = "Standard"

  depends_on = [terraform_data.guard]
}
