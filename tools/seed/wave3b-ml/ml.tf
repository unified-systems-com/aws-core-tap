# Wave 3b, SageMaker definitions: a pipeline, a model package group, a model card, a hub, a code repository, an app image
# configuration and two lifecycle configurations. Definitions only: no model, endpoint, notebook, training job or domain is created,
# so nothing runs and nothing bills by the hour.

data "aws_iam_policy_document" "sagemaker_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["sagemaker.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

# A role with no permissions: the pipeline only records it.
resource "aws_iam_role" "sagemaker" {
  name               = "seed-w3l-${var.run_id}-sagemaker-role"
  assume_role_policy = data.aws_iam_policy_document.sagemaker_assume.json

  depends_on = [terraform_data.guard]
}

resource "aws_sagemaker_pipeline" "seed" {
  pipeline_name         = "${local.prefix}-pipeline"
  pipeline_display_name = "${local.prefix}-pipeline"
  role_arn              = aws_iam_role.sagemaker.arn

  pipeline_definition = jsonencode({
    Version = "2020-12-01"
    Steps = [{
      Name      = "SeedFail"
      Type      = "Fail"
      Arguments = { ErrorMessage = "seed" }
    }]
  })
}

resource "aws_sagemaker_model_package_group" "seed" {
  model_package_group_name        = "${local.prefix}-mpg"
  model_package_group_description = "seed"
}

resource "aws_sagemaker_model_card" "seed" {
  model_card_name   = "${local.prefix}-card"
  model_card_status = "Draft"

  content = jsonencode({
    model_overview = { model_description = "seed" }
  })
}

resource "aws_sagemaker_hub" "seed" {
  hub_name        = "${local.prefix}-hub"
  hub_description = "seed"
}

resource "aws_sagemaker_code_repository" "seed" {
  code_repository_name = "${local.prefix}-repo"

  git_config {
    repository_url = "https://example.invalid/seed.git"
    branch         = "main"
  }
}

resource "aws_sagemaker_app_image_config" "seed" {
  app_image_config_name = "${local.prefix}-appimage"

  kernel_gateway_image_config {
    kernel_spec {
      name = "python3"
    }
  }
}

resource "aws_sagemaker_notebook_instance_lifecycle_configuration" "seed" {
  name     = "${local.prefix}-nblc"
  on_start = base64encode("#!/bin/bash\ntrue\n")
}

resource "aws_sagemaker_studio_lifecycle_config" "seed" {
  studio_lifecycle_config_name     = "${local.prefix}-studiolc"
  studio_lifecycle_config_app_type = "JupyterServer"
  studio_lifecycle_config_content  = base64encode("#!/bin/bash\ntrue\n")
}
