# Buckets are empty, private and destroyed with the wave (a destroy stops on an object it did not create, since buckets are not force-emptied).
resource "aws_s3_bucket" "ap" {
  bucket = "${local.prefix}-ap"

  depends_on = [terraform_data.guard]
}

# The flow log and the trail write objects into their own buckets (a delivery test file, log files), so these two are
# emptied when they are destroyed. Every other bucket here is not force-emptied and a destroy stops on a stray object.
resource "aws_s3_bucket" "flow" {
  bucket        = "${local.prefix}-flow"
  force_destroy = true

  depends_on = [terraform_data.guard]
}

resource "aws_s3_bucket" "trail" {
  bucket        = "${local.prefix}-trail"
  force_destroy = true

  depends_on = [terraform_data.guard]
}

resource "aws_s3_bucket" "report" {
  bucket = "${local.prefix}-report"

  depends_on = [terraform_data.guard]
}

data "aws_iam_policy_document" "trail_bucket" {
  statement {
    sid       = "AclCheck"
    actions   = ["s3:GetBucketAcl"]
    resources = [aws_s3_bucket.trail.arn]
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
  }
  statement {
    sid       = "Write"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.trail.arn}/AWSLogs/${data.aws_caller_identity.current.account_id}/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "s3:x-amz-acl"
      values   = ["bucket-owner-full-control"]
    }
  }
}

resource "aws_s3_bucket_policy" "trail" {
  bucket = aws_s3_bucket.trail.id
  policy = data.aws_iam_policy_document.trail_bucket.json
}

resource "aws_s3_access_point" "seed" {
  name   = "${local.prefix}-ap"
  bucket = aws_s3_bucket.ap.id
}

resource "aws_s3control_storage_lens_configuration" "seed" {
  config_id = "${local.prefix}-lens"

  storage_lens_configuration {
    enabled = true

    account_level {
      bucket_level {}
    }
  }
}

# S3 Access Grants: an instance, one location on the bucket, one grant to the seed role.
resource "aws_s3control_access_grants_instance" "seed" {
  depends_on = [terraform_data.guard]
}

resource "aws_s3control_access_grants_location" "seed" {
  iam_role_arn   = aws_iam_role.grants.arn
  location_scope = "s3://${aws_s3_bucket.ap.bucket}/*"

  depends_on = [aws_s3control_access_grants_instance.seed]
}

resource "aws_s3control_access_grant" "seed" {
  access_grants_location_id = aws_s3control_access_grants_location.seed.access_grants_location_id
  permission                = "READ"

  access_grants_location_configuration {
    s3_sub_prefix = "*"
  }

  grantee {
    grantee_type       = "IAM"
    grantee_identifier = aws_iam_role.grants.arn
  }
}
