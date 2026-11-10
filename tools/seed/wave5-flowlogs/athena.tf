# The customer-side summarising plumbing (aws-core-tap#218): a Glue table over the flow logs, a summary table the query
# appends to, an Athena workgroup, the query itself (a named query for a run by hand, and a schedule), and the role the
# schedule runs as. The collector never runs any of this; it would only read the summary objects.

resource "aws_s3_bucket" "work" { # NOSONAR: private, run-scoped and destroyed within the time box; only Athena writes to it
  bucket        = "${local.prefix}-work"
  force_destroy = true

  depends_on = [terraform_data.guard]
}

resource "aws_s3_bucket_public_access_block" "work" {
  bucket                  = aws_s3_bucket.work.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_glue_catalog_database" "flows" {
  name = replace("${local.prefix}_flows", "-", "_")

  depends_on = [terraform_data.guard]
}

locals {
  flow_prefix = "s3://${aws_s3_bucket.flow.bucket}/AWSLogs/aws-account-id=${data.aws_caller_identity.current.account_id}/aws-service=vpcflowlogs/aws-region=${data.aws_region.current.region}"
  # Parquet column names are the field names with `-` as `_`.
  raw_columns = {
    version = "int", account_id = "string", interface_id = "string", srcaddr = "string", dstaddr = "string",
    srcport = "int", dstport = "int", protocol = "bigint", packets = "bigint", bytes = "bigint", start = "bigint",
    end = "bigint", action = "string", log_status = "string", vpc_id = "string", subnet_id = "string",
    instance_id = "string", tcp_flags = "int", type = "string", pkt_srcaddr = "string", pkt_dstaddr = "string",
    flow_direction = "string", traffic_path = "int",
  }
  summary_columns = [
    ["interface_id", "string"], ["vpc_id", "string"], ["subnet_id", "string"], ["instance_id", "string"],
    ["flow_direction", "string"], ["action", "string"], ["client_address", "string"], ["server_address", "string"],
    ["server_port", "int"], ["protocol", "bigint"], ["packets", "bigint"], ["bytes", "bigint"], ["records", "bigint"],
    ["syn_seen", "boolean"], ["first_seen", "bigint"], ["last_seen", "bigint"],
  ]
}

resource "aws_glue_catalog_table" "raw" {
  name          = "flow_logs"
  database_name = aws_glue_catalog_database.flows.name
  table_type    = "EXTERNAL_TABLE"

  # Partition projection: Athena computes the partitions from these ranges, so there is no crawler and no partition to add.
  parameters = {
    "EXTERNAL"                  = "TRUE"
    "projection.enabled"        = "true"
    "projection.year.type"      = "integer"
    "projection.year.range"     = "2026,2036"
    "projection.month.type"     = "integer"
    "projection.month.range"    = "1,12"
    "projection.month.digits"   = "2"
    "projection.day.type"       = "integer"
    "projection.day.range"      = "1,31"
    "projection.day.digits"     = "2"
    "projection.hour.type"      = "integer"
    "projection.hour.range"     = "0,23"
    "projection.hour.digits"    = "2"
    "storage.location.template" = "${local.flow_prefix}/year=$${year}/month=$${month}/day=$${day}/hour=$${hour}/"
  }

  dynamic "partition_keys" {
    for_each = ["year", "month", "day", "hour"]
    content {
      name = partition_keys.value
      type = "string"
    }
  }

  storage_descriptor {
    location      = "${local.flow_prefix}/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    dynamic "columns" {
      for_each = local.raw_columns
      content {
        name = columns.key
        type = columns.value
      }
    }
  }
}

# The summaries: JSON lines, one partition per run (`window_end`), so a reader needs no Parquet library. Athena
# writes them gzipped (`.gz`; seen in the 2026-11-10 trial), so a reader must gunzip.
resource "aws_glue_catalog_table" "summary" {
  name          = "flow_summaries"
  database_name = aws_glue_catalog_database.flows.name
  table_type    = "EXTERNAL_TABLE"
  parameters    = { "EXTERNAL" = "TRUE" }

  partition_keys {
    name = "window_end"
    type = "string"
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.work.bucket}/summaries/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
    }

    dynamic "columns" {
      for_each = local.summary_columns
      content {
        name = columns.value[0]
        type = columns.value[1]
      }
    }
  }
}

resource "aws_athena_workgroup" "flows" {
  name          = "${local.prefix}-flows"
  force_destroy = true # its query history only; nothing outside this run's state

  configuration {
    enforce_workgroup_configuration = true

    result_configuration {
      output_location = "s3://${aws_s3_bucket.work.bucket}/athena-results/"
    }
  }

  depends_on = [terraform_data.guard]
}

locals {
  summarise_sql = templatefile("${path.module}/summarise.sql.tftpl", {
    database       = aws_glue_catalog_database.flows.name
    raw_table      = aws_glue_catalog_table.raw.name
    summary_table  = aws_glue_catalog_table.summary.name
    interface_ids  = var.filter_interface_ids
    instance_ids   = var.filter_instance_ids
    addresses      = var.filter_addresses
    ports          = var.filter_ports
    lookback_hours = var.lookback_hours
    window_start   = var.window_start
    window_end     = var.window_end
  })
}

resource "aws_athena_named_query" "summarise" {
  name      = "${local.prefix}-summarise"
  database  = aws_glue_catalog_database.flows.name
  workgroup = aws_athena_workgroup.flows.name
  query     = local.summarise_sql
}

# --- the schedule: EventBridge Scheduler calls Athena itself (a universal target), no function or workflow in between ---

data "aws_iam_policy_document" "scheduler_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "seed-w5f-${var.run_id}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_trust.json

  depends_on = [terraform_data.guard]
}

data "aws_iam_policy_document" "scheduler" {
  statement {
    sid       = "RunTheQuery"
    actions   = ["athena:StartQueryExecution", "athena:GetQueryExecution"]
    resources = [aws_athena_workgroup.flows.arn]
  }
  statement {
    sid     = "ReadAndAppendTheTables"
    actions = ["glue:GetDatabase", "glue:GetTable", "glue:GetPartition", "glue:GetPartitions", "glue:CreatePartition", "glue:BatchCreatePartition"]
    resources = [
      "arn:${data.aws_partition.current.partition}:glue:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:catalog",
      "arn:${data.aws_partition.current.partition}:glue:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:database/${aws_glue_catalog_database.flows.name}",
      "arn:${data.aws_partition.current.partition}:glue:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:table/${aws_glue_catalog_database.flows.name}/*",
    ]
  }
  statement {
    sid       = "ReadTheFlowLogs"
    actions   = ["s3:GetObject", "s3:ListBucket", "s3:GetBucketLocation"]
    resources = [aws_s3_bucket.flow.arn, "${aws_s3_bucket.flow.arn}/*"]
  }
  statement {
    sid       = "WriteSummariesAndResults"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:GetBucketLocation", "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"]
    resources = [aws_s3_bucket.work.arn, "${aws_s3_bucket.work.arn}/*"]
  }
}

resource "aws_iam_role_policy" "scheduler" {
  name   = "${local.prefix}-scheduler"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler.json
}

resource "aws_scheduler_schedule" "summarise" {
  name                = "${local.prefix}-summarise"
  schedule_expression = var.schedule_expression
  state               = var.schedule_state

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = "arn:${data.aws_partition.current.partition}:scheduler:::aws-sdk:athena:startQueryExecution"
    role_arn = aws_iam_role.scheduler.arn
    input = jsonencode({
      QueryString = local.summarise_sql
      WorkGroup   = aws_athena_workgroup.flows.name
    })
  }
}
