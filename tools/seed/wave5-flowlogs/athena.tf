# The customer-side summarising plumbing (aws-core-tap#218): a Glue table over the flow logs, a table over the summaries
# the query writes, an Athena workgroup, the query itself (rendered for a run by hand, and run by a schedule), and the
# role the schedule runs as. The collector never runs any of this; it would only read the summary objects.

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
    pkt_src_aws_service = "string", pkt_dst_aws_service = "string", next_hop_interface_id = "string",
  }
  summary_columns = [
    ["client_address", "string"], ["server_address", "string"], ["server_port", "int"], ["protocol", "bigint"],
    ["connections", "bigint"], ["decided_by_flags", "bigint"], ["decided_by_port", "bigint"], ["undecided", "bigint"],
    ["client_to_server_bytes", "bigint"], ["server_to_client_bytes", "bigint"], ["client_to_server_packets", "bigint"],
    ["server_to_client_packets", "bigint"], ["records", "bigint"], ["rejected_records", "bigint"],
    ["client_interface_id", "string"], ["client_instance_id", "string"], ["client_aws_service", "string"],
    ["server_interface_id", "string"], ["server_instance_id", "string"], ["server_aws_service", "string"],
    ["next_hop_interface_ids", "array<string>"], ["first_seen", "bigint"], ["last_seen", "bigint"], ["action", "string"],
    ["window_start", "string"], ["window_end", "string"],
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

# The summaries: JSON lines, one conversation per line, one prefix per run (`run=<run time>`), so a reader needs no
# Parquet library. UNLOAD writes them gzipped (`.gz`), so a reader must gunzip. The table is for a person querying them;
# the run's prefix is a projected partition the query names (`WHERE run = '...'`).
resource "aws_glue_catalog_table" "summary" {
  name          = "flow_summaries"
  database_name = aws_glue_catalog_database.flows.name
  table_type    = "EXTERNAL_TABLE"
  parameters = {
    "EXTERNAL"                  = "TRUE"
    "projection.enabled"        = "true"
    "projection.run.type"       = "injected"
    "storage.location.template" = "s3://${aws_s3_bucket.work.bucket}/summaries/run=$${run}/"
  }

  partition_keys {
    name = "run"
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
  # The query twice: for a run by hand at var.run_time, and for the schedule, which substitutes its own scheduled time
  # for the placeholder when it calls Athena. The run time names the output prefix and, without a fixed end, places the
  # window: its end is the hour boundary at or before the run time less the lag.
  run_times = { by_hand = var.run_time, scheduled = "<aws.scheduler.scheduled-time>" }
  window_end_sql = { for k, t in local.run_times : k => (
    var.window_end != "" ? "from_iso8601_timestamp('${var.window_end}')" :
    "date_trunc('hour', from_iso8601_timestamp('${t}') - INTERVAL '${var.lag_minutes}' MINUTE)"
  ) }
  window_start_sql = { for k, t in local.run_times : k => (
    var.window_start != "" ? "from_iso8601_timestamp('${var.window_start}')" :
    "(${local.window_end_sql[k]}) - INTERVAL '${var.lookback_hours}' HOUR"
  ) }
  output_names = { by_hand = var.output_name, scheduled = "summaries" }
  summarise = { for k, t in local.run_times : k => templatefile("${path.module}/summarise.sql.tftpl", {
    database           = aws_glue_catalog_database.flows.name
    raw_table          = aws_glue_catalog_table.raw.name
    output_location    = "s3://${aws_s3_bucket.work.bucket}/${local.output_names[k]}/run=${t}/"
    window_start_sql   = local.window_start_sql[k]
    window_end_sql     = local.window_end_sql[k]
    interface_ids      = var.filter_interface_ids
    instance_ids       = var.filter_instance_ids
    addresses          = var.filter_addresses
    sources            = var.filter_sources
    destinations       = var.filter_destinations
    pairs              = var.filter_pairs
    endpoint_addresses = distinct(concat(var.filter_sources, var.filter_destinations, [for p in var.filter_pairs : p.source], [for p in var.filter_pairs : p.destination]))
    ports              = var.filter_ports
  }) }
  # A run by hand needs a run time; without one there is no query to render.
  summarise_sql = var.run_time == "" ? null : local.summarise["by_hand"]
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
    # Scheduler's confused-deputy guidance names the schedule group, never a schedule, as the source.
    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = ["arn:${data.aws_partition.current.partition}:scheduler:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:schedule-group/default"]
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
    sid     = "ReadTheTables"
    actions = ["glue:GetDatabase", "glue:GetTable", "glue:GetPartition", "glue:GetPartitions"]
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
    # jsonencode writes < and > as < and >, which hides the scheduled-time keyword from Scheduler (seen in
    # the 2026-11-10 re-trial: Athena received the keyword itself); putting them back lets Scheduler replace it.
    input = replace(replace(jsonencode({
      QueryString = local.summarise["scheduled"]
      WorkGroup   = aws_athena_workgroup.flows.name
    }), "\\u003c", "<"), "\\u003e", ">")
  }
}
