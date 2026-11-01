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
resource "aws_s3_bucket" "a" {
  bucket        = "${local.prefix}-bucket-a"
  force_destroy = true
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
resource "aws_s3_bucket" "b" {
  bucket        = "${local.prefix}-bucket-b"
  force_destroy = true

  depends_on = [terraform_data.guard]
}

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
