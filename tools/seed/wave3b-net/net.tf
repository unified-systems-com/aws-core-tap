# Wave 3b, DNS and streaming: Route 53 Resolver (an outbound endpoint, a forwarding rule, a query log configuration, DNS Firewall,
# and the three per-VPC settings), a Kinesis stream, a CloudWatch Logs destination with a subscription filter, and a Firehose delivery
# stream with a CloudWatch metric stream. The hourly charges are the resolver endpoint's two network interfaces and the stream's one
# shard; the cost note prices them. Nothing is sent: no query is forwarded, no record is put, and the metric stream filters on a
# namespace no metric is published to, so the delivery bucket stays empty.

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "seed" {
  cidr_block           = "10.96.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  depends_on = [terraform_data.guard]
}

resource "aws_subnet" "a" {
  vpc_id            = aws_vpc.seed.id
  cidr_block        = "10.96.1.0/24"
  availability_zone = data.aws_availability_zones.available.names[0]
}

resource "aws_subnet" "b" {
  vpc_id            = aws_vpc.seed.id
  cidr_block        = "10.96.2.0/24"
  availability_zone = data.aws_availability_zones.available.names[1]
}

# One group with no rules at all.
resource "aws_security_group" "seed" {
  name        = "${local.prefix}-sg"
  description = "seed wave 3b net: no rules"
  vpc_id      = aws_vpc.seed.id
}

# --- Route 53 Resolver: an outbound endpoint and a rule that forwards one made-up domain to a documentation address ---

resource "aws_route53_resolver_endpoint" "out" {
  name               = "${local.prefix}-out"
  direction          = "OUTBOUND"
  security_group_ids = [aws_security_group.seed.id]

  ip_address {
    subnet_id = aws_subnet.a.id
  }

  ip_address {
    subnet_id = aws_subnet.b.id
  }

  depends_on = [terraform_data.guard]
}

resource "aws_route53_resolver_rule" "seed" {
  name                 = "${local.prefix}-rule"
  domain_name          = "${local.prefix}.example.invalid"
  rule_type            = "FORWARD"
  resolver_endpoint_id = aws_route53_resolver_endpoint.out.id

  target_ip {
    ip = "192.0.2.53"
  }
}

resource "aws_cloudwatch_log_group" "queries" {
  name              = "/seed/${local.prefix}-queries"
  retention_in_days = 1 # NOSONAR

  depends_on = [terraform_data.guard]
}

resource "aws_route53_resolver_query_log_config" "seed" {
  name            = "${local.prefix}-querylog"
  destination_arn = aws_cloudwatch_log_group.queries.arn
}

# --- DNS Firewall: a domain list, a rule group with one rule, an association, and the per-VPC settings ---

resource "aws_route53_resolver_firewall_domain_list" "seed" {
  name    = "${local.prefix}-domains"
  domains = ["seed.example.invalid"]

  depends_on = [terraform_data.guard]
}

resource "aws_route53_resolver_firewall_rule_group" "seed" {
  name = "${local.prefix}-rulegroup"

  depends_on = [terraform_data.guard]
}

resource "aws_route53_resolver_firewall_rule" "seed" {
  name                    = "${local.prefix}-block"
  action                  = "BLOCK"
  block_response          = "NXDOMAIN"
  firewall_domain_list_id = aws_route53_resolver_firewall_domain_list.seed.id
  firewall_rule_group_id  = aws_route53_resolver_firewall_rule_group.seed.id
  priority                = 100
}

resource "aws_route53_resolver_firewall_rule_group_association" "seed" {
  name                   = "${local.prefix}-association"
  firewall_rule_group_id = aws_route53_resolver_firewall_rule_group.seed.id
  vpc_id                 = aws_vpc.seed.id
  priority               = 101

  depends_on = [aws_route53_resolver_firewall_rule.seed]
}

resource "aws_route53_resolver_firewall_config" "seed" {
  resource_id        = aws_vpc.seed.id
  firewall_fail_open = "DISABLED"
}

resource "aws_route53_resolver_config" "seed" {
  resource_id              = aws_vpc.seed.id
  autodefined_reverse_flag = "DISABLE"
}

resource "aws_route53_resolver_dnssec_config" "seed" {
  resource_id = aws_vpc.seed.id
}

# --- Kinesis: one provisioned shard, a CloudWatch Logs destination in front of it, and a subscription filter to the destination ---

# An empty stream that lives for under an hour and is never put to; encrypting it would need the destination's role to be allowed the key too.
# nosemgrep: terraform.aws.security.aws-kinesis-stream-unencrypted.aws-kinesis-stream-unencrypted
resource "aws_kinesis_stream" "seed" { # NOSONAR: empty, run-scoped and destroyed within the hour; nothing is ever put
  name             = "${local.prefix}-stream"
  shard_count      = 1
  retention_period = 24

  stream_mode_details {
    stream_mode = "PROVISIONED"
  }

  depends_on = [terraform_data.guard]
}

data "aws_iam_policy_document" "logs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["logs.${data.aws_region.current.region}.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "logs" {
  name               = "seed-w3n-${var.run_id}-logs-role"
  assume_role_policy = data.aws_iam_policy_document.logs_assume.json

  depends_on = [terraform_data.guard]
}

resource "aws_iam_role_policy" "logs" {
  name = "${local.prefix}-logs-put"
  role = aws_iam_role.logs.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["kinesis:PutRecord"]
      Resource = [aws_kinesis_stream.seed.arn]
    }]
  })
}

resource "aws_cloudwatch_log_destination" "seed" {
  name       = "${local.prefix}-destination"
  role_arn   = aws_iam_role.logs.arn
  target_arn = aws_kinesis_stream.seed.arn

  depends_on = [aws_iam_role_policy.logs]
}

resource "aws_cloudwatch_log_destination_policy" "seed" {
  destination_name = aws_cloudwatch_log_destination.seed.name

  access_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { AWS = data.aws_caller_identity.current.account_id }
      Action    = "logs:PutSubscriptionFilter"
      Resource  = aws_cloudwatch_log_destination.seed.arn
    }]
  })
}

resource "aws_cloudwatch_log_group" "source" {
  name              = "/seed/${local.prefix}-source"
  retention_in_days = 1 # NOSONAR

  depends_on = [terraform_data.guard]
}

resource "aws_cloudwatch_log_subscription_filter" "seed" {
  name            = "${local.prefix}-subscription"
  log_group_name  = aws_cloudwatch_log_group.source.name
  filter_pattern  = "seedpattern"
  destination_arn = aws_cloudwatch_log_destination.seed.arn

  depends_on = [aws_cloudwatch_log_destination_policy.seed]
}

# --- Firehose and a metric stream: the delivery bucket stays empty because the stream's filter names a namespace nothing publishes to ---

resource "aws_s3_bucket" "delivery" { # NOSONAR: empty, run-scoped and destroyed within the hour; no object is ever written
  bucket = "${local.prefix}-delivery"

  depends_on = [terraform_data.guard]
}

resource "aws_s3_bucket_public_access_block" "delivery" {
  bucket                  = aws_s3_bucket.delivery.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

data "aws_iam_policy_document" "firehose_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["firehose.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "sts:ExternalId"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "firehose" {
  name               = "seed-w3n-${var.run_id}-firehose-role"
  assume_role_policy = data.aws_iam_policy_document.firehose_assume.json

  depends_on = [terraform_data.guard]
}

resource "aws_iam_role_policy" "firehose" {
  name = "${local.prefix}-firehose-s3"
  role = aws_iam_role.firehose.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:AbortMultipartUpload", "s3:GetBucketLocation", "s3:ListBucket", "s3:ListBucketMultipartUploads", "s3:PutObject"]
      Resource = [aws_s3_bucket.delivery.arn, "${aws_s3_bucket.delivery.arn}/*"]
    }]
  })
}

resource "aws_kinesis_firehose_delivery_stream" "seed" { # NOSONAR: encryption is the default; the stream carries nothing
  name        = "${local.prefix}-firehose"
  destination = "extended_s3"

  extended_s3_configuration {
    role_arn           = aws_iam_role.firehose.arn
    bucket_arn         = aws_s3_bucket.delivery.arn
    buffering_size     = 5
    buffering_interval = 900
  }

  depends_on = [aws_iam_role_policy.firehose]
}

data "aws_iam_policy_document" "metrics_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["streams.metrics.cloudwatch.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "metrics" {
  name               = "seed-w3n-${var.run_id}-metrics-role"
  assume_role_policy = data.aws_iam_policy_document.metrics_assume.json

  depends_on = [terraform_data.guard]
}

resource "aws_iam_role_policy" "metrics" {
  name = "${local.prefix}-metrics-put"
  role = aws_iam_role.metrics.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["firehose:PutRecord", "firehose:PutRecordBatch"]
      Resource = [aws_kinesis_firehose_delivery_stream.seed.arn]
    }]
  })
}

resource "aws_cloudwatch_metric_stream" "seed" {
  name          = "${local.prefix}-metrics"
  role_arn      = aws_iam_role.metrics.arn
  firehose_arn  = aws_kinesis_firehose_delivery_stream.seed.arn
  output_format = "json"

  include_filter {
    namespace = "SeedW3n${var.run_id}"
  }

  depends_on = [aws_iam_role_policy.metrics]
}
