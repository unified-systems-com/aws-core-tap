# Wave 3b, data and application services: Glue, Athena, Step Functions, AppConfig, the DocumentDB, Neptune and MemoryDB
# configuration objects (no database), Service Catalog and Managed Prometheus. Everything here is a
# definition: nothing is run, no cluster or node is created, no query is made. All of it is free while idle.

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "seed" {
  cidr_block = "10.97.0.0/16"

  depends_on = [terraform_data.guard]
}

resource "aws_subnet" "a" {
  vpc_id            = aws_vpc.seed.id
  cidr_block        = "10.97.1.0/24"
  availability_zone = data.aws_availability_zones.available.names[0]
}

resource "aws_subnet" "b" {
  vpc_id            = aws_vpc.seed.id
  cidr_block        = "10.97.2.0/24"
  availability_zone = data.aws_availability_zones.available.names[1]
}

# --- IAM: one role for Glue and one for Step Functions; neither is ever assumed ---

data "aws_iam_policy_document" "glue_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["glue.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "glue" {
  name               = "seed-w3d-${var.run_id}-glue-role"
  assume_role_policy = data.aws_iam_policy_document.glue_assume.json

  depends_on = [terraform_data.guard]
}

data "aws_iam_policy_document" "sfn_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.${data.aws_region.current.region}.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "sfn" {
  name               = "seed-w3d-${var.run_id}-sfn-role"
  assume_role_policy = data.aws_iam_policy_document.sfn_assume.json

  depends_on = [terraform_data.guard]
}

# --- Glue: a database and table, a registry and schema, a crawler, a job, a trigger, a workflow and a security configuration ---

# The crawler checks that its target exists, so the bucket is created; it stays empty and the crawler is never started.
resource "aws_s3_bucket" "nothing" { # NOSONAR: empty, run-scoped and destroyed within the hour; no object is ever written
  bucket = "${local.prefix}-nothing"

  depends_on = [terraform_data.guard]
}

resource "aws_s3_bucket_public_access_block" "nothing" {
  bucket                  = aws_s3_bucket.nothing.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_glue_catalog_database" "seed" {
  name = replace("${local.prefix}-db", "-", "_")

  depends_on = [terraform_data.guard]
}

resource "aws_glue_catalog_table" "seed" {
  name          = replace("${local.prefix}-table", "-", "_")
  database_name = aws_glue_catalog_database.seed.name
  table_type    = "EXTERNAL_TABLE"

  storage_descriptor {
    location = "s3://${local.prefix}-nothing/table/"

    columns {
      name = "id"
      type = "string"
    }
  }
}

resource "aws_glue_registry" "seed" {
  registry_name = "${local.prefix}-registry"

  depends_on = [terraform_data.guard]
}

resource "aws_glue_schema" "seed" {
  schema_name       = "${local.prefix}-schema"
  registry_arn      = aws_glue_registry.seed.arn
  data_format       = "AVRO"
  compatibility     = "NONE"
  schema_definition = jsonencode({ type = "record", name = "Seed", fields = [{ name = "id", type = "string" }] })
}

resource "aws_glue_crawler" "seed" {
  name          = "${local.prefix}-crawler"
  database_name = aws_glue_catalog_database.seed.name
  role          = aws_iam_role.glue.arn

  s3_target {
    path = "s3://${aws_s3_bucket.nothing.bucket}/crawl/"
  }

  depends_on = [terraform_data.guard]
}

resource "aws_glue_job" "seed" {
  name              = "${local.prefix}-job"
  role_arn          = aws_iam_role.glue.arn
  glue_version      = "4.0"
  worker_type       = "G.1X"
  number_of_workers = 2

  command {
    name            = "glueetl"
    script_location = "s3://${local.prefix}-nothing/job.py"
    python_version  = "3"
  }

  depends_on = [terraform_data.guard]
}

resource "aws_glue_trigger" "seed" {
  name = "${local.prefix}-trigger"
  type = "ON_DEMAND"

  actions {
    job_name = aws_glue_job.seed.name
  }
}

resource "aws_glue_workflow" "seed" {
  name = "${local.prefix}-workflow"

  depends_on = [terraform_data.guard]
}

resource "aws_glue_security_configuration" "seed" {
  name = "${local.prefix}-security"

  encryption_configuration {
    cloudwatch_encryption {
      cloudwatch_encryption_mode = "DISABLED"
    }

    job_bookmarks_encryption {
      job_bookmarks_encryption_mode = "DISABLED"
    }

    s3_encryption {
      s3_encryption_mode = "SSE-S3"
    }
  }

  depends_on = [terraform_data.guard]
}

# --- Athena: a work group, a Glue data catalog and a saved query ---

resource "aws_athena_workgroup" "seed" {
  name = "${local.prefix}-wg"

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = false
  }

  depends_on = [terraform_data.guard]
}

resource "aws_athena_data_catalog" "seed" {
  name        = "${local.prefix}-catalog"
  description = "seed wave 3b data"
  type        = "GLUE"

  parameters = {
    "catalog-id" = data.aws_caller_identity.current.account_id
  }

  depends_on = [terraform_data.guard]
}

resource "aws_athena_named_query" "seed" {
  name      = "${local.prefix}-query"
  database  = aws_glue_catalog_database.seed.name
  workgroup = aws_athena_workgroup.seed.id
  query     = "SELECT 1"
}

# --- Step Functions: an activity, a state machine that is never started, and an alias to its published version ---

resource "aws_sfn_activity" "seed" {
  name = "${local.prefix}-activity"

  depends_on = [terraform_data.guard]
}

resource "aws_sfn_state_machine" "seed" {
  name     = "${local.prefix}-machine"
  role_arn = aws_iam_role.sfn.arn
  publish  = true

  definition = jsonencode({
    StartAt = "Done"
    States  = { Done = { Type = "Pass", End = true } }
  })

  depends_on = [terraform_data.guard]
}

resource "aws_sfn_alias" "seed" {
  name = "seed"

  routing_configuration {
    state_machine_version_arn = aws_sfn_state_machine.seed.state_machine_version_arn
    weight                    = 100
  }
}

# --- AppConfig ---

resource "aws_appconfig_application" "seed" {
  name = "${local.prefix}-app"

  depends_on = [terraform_data.guard]
}

resource "aws_appconfig_environment" "seed" {
  name           = "${local.prefix}-env"
  application_id = aws_appconfig_application.seed.id
}

resource "aws_appconfig_configuration_profile" "seed" {
  name           = "${local.prefix}-profile"
  application_id = aws_appconfig_application.seed.id
  location_uri   = "hosted"
}

resource "aws_appconfig_deployment_strategy" "seed" {
  name                           = "${local.prefix}-strategy"
  deployment_duration_in_minutes = 0
  growth_factor                  = 100
  replicate_to                   = "NONE"

  depends_on = [terraform_data.guard]
}

# --- DocumentDB, Neptune and MemoryDB: the configuration objects and an empty global cluster; no database ---

resource "aws_sns_topic" "events" { # NOSONAR: empty, run-scoped and destroyed within the hour; no message is ever published
  name = "${local.prefix}-events"

  depends_on = [terraform_data.guard]
}

resource "aws_docdb_subnet_group" "seed" {
  name       = "${local.prefix}-docdb"
  subnet_ids = [aws_subnet.a.id, aws_subnet.b.id]

  depends_on = [terraform_data.guard]
}

resource "aws_docdb_cluster_parameter_group" "seed" {
  name   = "${local.prefix}-docdb"
  family = "docdb5.0"

  depends_on = [terraform_data.guard]
}

resource "aws_docdb_event_subscription" "seed" {
  name          = "${local.prefix}-docdb"
  sns_topic_arn = aws_sns_topic.events.arn
  source_type   = "db-cluster"
}

resource "aws_docdb_global_cluster" "seed" {
  global_cluster_identifier = "${local.prefix}-docdb"
  engine                    = "docdb"
  engine_version            = "5.0.0"

  depends_on = [terraform_data.guard]
}

resource "aws_neptune_subnet_group" "seed" {
  name       = "${local.prefix}-neptune"
  subnet_ids = [aws_subnet.a.id, aws_subnet.b.id]

  depends_on = [terraform_data.guard]
}

resource "aws_neptune_cluster_parameter_group" "seed" {
  name   = "${local.prefix}-neptune"
  family = "neptune1.4"

  depends_on = [terraform_data.guard]
}

resource "aws_neptune_parameter_group" "seed" {
  name   = "${local.prefix}-neptune"
  family = "neptune1.4"

  depends_on = [terraform_data.guard]
}

resource "aws_neptune_event_subscription" "seed" {
  name          = "${local.prefix}-neptune"
  sns_topic_arn = aws_sns_topic.events.arn
  source_type   = "db-cluster"
}

resource "aws_memorydb_subnet_group" "seed" {
  name       = "${local.prefix}-memorydb"
  subnet_ids = [aws_subnet.a.id, aws_subnet.b.id]

  depends_on = [terraform_data.guard]
}

resource "aws_memorydb_parameter_group" "seed" {
  name   = "${local.prefix}-memorydb"
  family = "memorydb_redis7"

  depends_on = [terraform_data.guard]
}

resource "aws_memorydb_user" "seed" {
  user_name     = "${local.prefix}-user"
  access_string = "on ~* &* +@all"

  authentication_mode {
    type = "iam"
  }

  depends_on = [terraform_data.guard]
}

resource "aws_memorydb_acl" "seed" {
  name       = "${local.prefix}-acl"
  user_names = [aws_memorydb_user.seed.user_name]
}

# --- Service Catalog and Managed Prometheus ---

resource "aws_servicecatalog_portfolio" "seed" {
  name          = "${local.prefix}-portfolio"
  provider_name = "seed"

  depends_on = [terraform_data.guard]
}

resource "aws_servicecatalog_tag_option" "seed" {
  key   = "seed-w3d"
  value = var.run_id

  depends_on = [terraform_data.guard]
}

resource "aws_servicecatalog_service_action" "seed" {
  name = "${local.prefix}-action"

  definition {
    name    = "AWS-RestartEC2Instance"
    version = "1"
  }

  depends_on = [terraform_data.guard]
}

resource "aws_prometheus_workspace" "seed" {
  alias = "${local.prefix}-workspace"

  depends_on = [terraform_data.guard]
}

resource "aws_prometheus_rule_group_namespace" "seed" {
  name         = "${local.prefix}-rules"
  workspace_id = aws_prometheus_workspace.seed.id

  data = <<-YAML
    groups:
      - name: seed
        rules:
          - record: seed:one
            expr: vector(1)
  YAML
}
