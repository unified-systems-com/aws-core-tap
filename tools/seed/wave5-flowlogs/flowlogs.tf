# Flow logs to S3 in the shape the summarising query reads: Parquet, Hive-style partitions, one per hour.

resource "aws_s3_bucket" "flow" { # NOSONAR: private, run-scoped and destroyed within the time box; only the flow log service writes to it
  bucket        = "${local.prefix}-flow"
  force_destroy = true

  depends_on = [terraform_data.guard]
}

resource "aws_s3_bucket_public_access_block" "flow" {
  bucket                  = aws_s3_bucket.flow.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

locals {
  # The fields the default format lacks are the ones the summary needs: interface, VPC, subnet and instance ids, the TCP
  # flags (who opened the connection) and the direction; and, where the region has them, the AWS service an address
  # belongs to and the interface at the other end of the hop. `$$` is a literal `$` in HCL.
  flow_fields = concat([
    "version", "account-id", "interface-id", "srcaddr", "dstaddr", "srcport", "dstport", "protocol", "packets", "bytes",
    "start", "end", "action", "log-status", "vpc-id", "subnet-id", "instance-id", "tcp-flags", "type", "pkt-srcaddr",
    "pkt-dstaddr", "flow-direction", "traffic-path",
  ], var.newer_fields ? ["pkt-src-aws-service", "pkt-dst-aws-service", "next-hop-interface-id"] : [])
  flow_log_format = join(" ", [for f in local.flow_fields : "$${${f}}"])
}

resource "aws_flow_log" "seed" {
  vpc_id                   = aws_vpc.seed.id
  traffic_type             = "ALL"
  log_destination_type     = "s3"
  log_destination          = aws_s3_bucket.flow.arn
  log_format               = local.flow_log_format
  max_aggregation_interval = var.aggregation_interval

  destination_options {
    file_format                = "parquet"
    hive_compatible_partitions = true
    per_hour_partition         = true
  }

  depends_on = [aws_s3_bucket_public_access_block.flow]
}
