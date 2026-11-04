# Wave 3b, application and developer services: Lambda (a layer and an alias beside a function), Batch (an unmanaged compute
# environment, a queue, a job definition and a scheduling policy), CodeBuild, CodePipeline, Cloud Map and Network Manager.
# Everything here is a definition: nothing is invoked, built, queued or run, and nothing bills while idle.

resource "aws_vpc" "seed" {
  cidr_block = "10.98.0.0/16"

  depends_on = [terraform_data.guard]
}

# --- IAM: a role each for Lambda, Batch, CodeBuild and CodePipeline; none is ever assumed ---

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name               = "seed-w3v-${var.run_id}-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json

  depends_on = [terraform_data.guard]
}

data "aws_iam_policy_document" "batch_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["batch.amazonaws.com"]
    }
  }
}

# Batch asks for a service role even for an unmanaged environment, and checks that the role may read log groups; it is
# never used to run anything.
resource "aws_iam_role" "batch" {
  name               = "seed-w3v-${var.run_id}-batch-role"
  assume_role_policy = data.aws_iam_policy_document.batch_assume.json

  depends_on = [terraform_data.guard]
}

resource "aws_iam_role_policy_attachment" "batch" {
  role       = aws_iam_role.batch.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AWSBatchServiceRole"
}

data "aws_iam_policy_document" "codebuild_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["codebuild.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "codebuild" {
  name               = "seed-w3v-${var.run_id}-codebuild-role"
  assume_role_policy = data.aws_iam_policy_document.codebuild_assume.json

  depends_on = [terraform_data.guard]
}

data "aws_iam_policy_document" "pipeline_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["codepipeline.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "pipeline" {
  name               = "seed-w3v-${var.run_id}-pipeline-role"
  assume_role_policy = data.aws_iam_policy_document.pipeline_assume.json

  depends_on = [terraform_data.guard]
}

resource "aws_iam_role_policy" "pipeline" {
  name = "${local.prefix}-pipeline-bucket"
  role = aws_iam_role.pipeline.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetBucketVersioning", "s3:GetObject", "s3:GetObjectVersion", "s3:PutObject"]
      Resource = [aws_s3_bucket.pipeline.arn, "${aws_s3_bucket.pipeline.arn}/*"]
    }]
  })
}

# --- Lambda: a function that is never invoked, with a layer and an alias ---

data "archive_file" "fn" {
  type        = "zip"
  output_path = "${path.module}/.build/fn.zip"

  source {
    filename = "index.py"
    content  = "def handler(event, context):\n    return {\"seed\": \"wave3b-dev\"}\n"
  }
}

# The function is never invoked, so there is nothing to trace.
# nosemgrep: terraform.aws.security.aws-lambda-x-ray-tracing-not-active.aws-lambda-x-ray-tracing-not-active
resource "aws_lambda_function" "seed" {
  function_name    = "${local.prefix}-fn"
  role             = aws_iam_role.lambda.arn
  runtime          = "python3.12"
  handler          = "index.handler"
  memory_size      = 128
  timeout          = 3
  publish          = true
  filename         = data.archive_file.fn.output_path
  source_code_hash = data.archive_file.fn.output_base64sha256

  depends_on = [terraform_data.guard]
}

resource "aws_lambda_layer_version" "seed" {
  layer_name          = "${local.prefix}-layer"
  compatible_runtimes = ["python3.12"]
  filename            = data.archive_file.fn.output_path
  source_code_hash    = data.archive_file.fn.output_base64sha256

  depends_on = [terraform_data.guard]
}

resource "aws_lambda_alias" "seed" {
  name             = "seed"
  function_name    = aws_lambda_function.seed.function_name
  function_version = aws_lambda_function.seed.version
}

# --- Batch: nothing is submitted, and the compute environment is unmanaged, so no instance is ever started ---

resource "aws_batch_compute_environment" "seed" {
  name         = "${local.prefix}-compute"
  type         = "UNMANAGED"
  state        = "ENABLED"
  service_role = aws_iam_role.batch.arn

  depends_on = [aws_iam_role_policy_attachment.batch]
}

resource "aws_batch_scheduling_policy" "seed" {
  name = "${local.prefix}-sched"

  fair_share_policy {
    share_decay_seconds = 3600
  }

  depends_on = [terraform_data.guard]
}

resource "aws_batch_job_queue" "seed" {
  name                  = "${local.prefix}-queue"
  state                 = "ENABLED"
  priority              = 1
  scheduling_policy_arn = aws_batch_scheduling_policy.seed.arn

  compute_environment_order {
    order               = 1
    compute_environment = aws_batch_compute_environment.seed.arn
  }
}

resource "aws_batch_job_definition" "seed" {
  name = "${local.prefix}-job"
  type = "container"

  container_properties = jsonencode({
    image   = "public.ecr.aws/docker/library/busybox:latest"
    command = ["true"]
    resourceRequirements = [
      { type = "VCPU", value = "1" },
      { type = "MEMORY", value = "512" },
    ]
  })

  depends_on = [terraform_data.guard]
}

# --- CodeBuild: a project with no source and a report group that exports nowhere; nothing is built ---

resource "aws_codebuild_project" "seed" {
  name         = "${local.prefix}-build"
  service_role = aws_iam_role.codebuild.arn

  artifacts {
    type = "NO_ARTIFACTS"
  }

  environment {
    compute_type = "BUILD_GENERAL1_SMALL"
    image        = "aws/codebuild/standard:7.0"
    type         = "LINUX_CONTAINER"
  }

  source {
    type      = "NO_SOURCE"
    buildspec = "version: 0.2\nphases:\n  build:\n    commands:\n      - 'true'\n"
  }

  depends_on = [terraform_data.guard]
}

resource "aws_codebuild_report_group" "seed" {
  name = "${local.prefix}-reports"
  type = "TEST"

  export_config {
    type = "NO_EXPORT"
  }

  depends_on = [terraform_data.guard]
}

# --- CodePipeline: an S3 source and a manual approval. The one execution it starts at creation fails (the object is not there) and bills nothing. ---

resource "aws_s3_bucket" "pipeline" { # NOSONAR: empty, run-scoped and destroyed within the hour; nothing is ever written
  bucket = "${local.prefix}-pipeline"

  depends_on = [terraform_data.guard]
}

resource "aws_s3_bucket_versioning" "pipeline" {
  bucket = aws_s3_bucket.pipeline.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "pipeline" {
  bucket                  = aws_s3_bucket.pipeline.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_codepipeline" "seed" {
  name          = "${local.prefix}-pipeline"
  role_arn      = aws_iam_role.pipeline.arn
  pipeline_type = "V1"

  artifact_store {
    location = aws_s3_bucket.pipeline.bucket
    type     = "S3"
  }

  stage {
    name = "Source"

    action {
      name             = "Source"
      category         = "Source"
      owner            = "AWS"
      provider         = "S3"
      version          = "1"
      output_artifacts = ["source"]

      configuration = {
        S3Bucket             = aws_s3_bucket.pipeline.bucket
        S3ObjectKey          = "source.zip"
        PollForSourceChanges = "false"
      }
    }
  }

  stage {
    name = "Approve"

    action {
      name     = "Approve"
      category = "Approval"
      owner    = "AWS"
      provider = "Manual"
      version  = "1"
    }
  }

  depends_on = [aws_iam_role_policy.pipeline, aws_s3_bucket_versioning.pipeline]
}

resource "aws_codepipeline_custom_action_type" "seed" {
  category      = "Build"
  provider_name = "SeedW3v${var.run_id}"
  version       = "1"

  input_artifact_details {
    maximum_count = 1
    minimum_count = 0
  }

  output_artifact_details {
    maximum_count = 1
    minimum_count = 0
  }

  depends_on = [terraform_data.guard]
}

# --- Cloud Map: a private namespace, an HTTP namespace and a service in the private one ---

resource "aws_service_discovery_private_dns_namespace" "seed" {
  name = "${local.prefix}.example.invalid"
  vpc  = aws_vpc.seed.id

  depends_on = [terraform_data.guard]
}

resource "aws_service_discovery_http_namespace" "seed" {
  name = "${local.prefix}-http"

  depends_on = [terraform_data.guard]
}

resource "aws_service_discovery_service" "seed" {
  name = "${local.prefix}-service"

  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.seed.id

    dns_records {
      ttl  = 10
      type = "A"
    }
  }
}

# --- Network Manager: a global network with a site, a device and a link ---

resource "aws_networkmanager_global_network" "seed" {
  description = "${local.prefix} global network"

  depends_on = [terraform_data.guard]
}

resource "aws_networkmanager_site" "seed" {
  global_network_id = aws_networkmanager_global_network.seed.id
  description       = "${local.prefix} site"
}

resource "aws_networkmanager_device" "seed" {
  global_network_id = aws_networkmanager_global_network.seed.id
  site_id           = aws_networkmanager_site.seed.id
  description       = "${local.prefix} device"
}

resource "aws_networkmanager_link" "seed" {
  global_network_id = aws_networkmanager_global_network.seed.id
  site_id           = aws_networkmanager_site.seed.id
  description       = "${local.prefix} link"

  bandwidth {
    download_speed = 10
    upload_speed   = 10
  }
}
