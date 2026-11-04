# Wave 3b, more small definitions that cost nothing while idle, among them the types whose key the collector builds as
# <account>/<region>/...: OpenSearch Serverless access, security and lifecycle policies (no collection) and an EMR security
# configuration. Also a Route 53 reusable delegation set, a Direct Connect gateway, a CodeDeploy deployment configuration and DAX
# subnet and parameter groups (no cluster). Nothing is invoked or attached.

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "seed" {
  cidr_block = "10.92.0.0/16"

  depends_on = [terraform_data.guard]
}

resource "aws_subnet" "a" {
  vpc_id            = aws_vpc.seed.id
  cidr_block        = "10.92.1.0/24"
  availability_zone = data.aws_availability_zones.available.names[0]
}

# --- OpenSearch Serverless policies: a name pattern that matches no collection, so nothing is governed ---

resource "aws_opensearchserverless_security_policy" "encryption" {
  name = "seed-w3z-${substr(var.run_id, 3, 8)}-enc"
  type = "encryption"

  policy = jsonencode({
    Rules = [{
      ResourceType = "collection"
      Resource     = ["collection/seed-w3z-${var.run_id}-none"]
    }]
    AWSOwnedKey = true
  })
}

resource "aws_opensearchserverless_access_policy" "seed" {
  name = "seed-w3z-${substr(var.run_id, 3, 8)}-acc"
  type = "data"

  policy = jsonencode([{
    Rules = [{
      ResourceType = "index"
      Resource     = ["index/seed-w3z-${var.run_id}-none/*"]
      Permission   = ["aoss:ReadDocument"]
    }]
    Principal = ["arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:root"]
  }])
}

resource "aws_opensearchserverless_lifecycle_policy" "seed" {
  name = "seed-w3z-${substr(var.run_id, 3, 8)}-lc"
  type = "retention"

  policy = jsonencode({
    Rules = [{
      ResourceType      = "index"
      Resource          = ["index/seed-w3z-${var.run_id}-none/*"]
      MinIndexRetention = "30d"
    }]
  })
}

# --- EMR ---

resource "aws_emr_security_configuration" "seed" {
  name = "${local.prefix}-emr"

  configuration = jsonencode({
    EncryptionConfiguration = {
      EnableInTransitEncryption = false
      EnableAtRestEncryption    = false
    }
  })
}

# --- Route 53, Direct Connect, CodeDeploy ---

resource "aws_route53_delegation_set" "seed" {
  reference_name = substr(local.prefix, 0, 32)
}

resource "aws_dx_gateway" "seed" {
  name            = "${local.prefix}-dxgw"
  amazon_side_asn = "64512"

  depends_on = [terraform_data.guard]
}

resource "aws_codedeploy_deployment_config" "seed" {
  deployment_config_name = "${local.prefix}-deploy"

  minimum_healthy_hosts {
    type  = "HOST_COUNT"
    value = 0
  }

  depends_on = [terraform_data.guard]
}

# --- DAX groups ---

resource "aws_dax_subnet_group" "seed" {
  name       = "${local.prefix}-dax"
  subnet_ids = [aws_subnet.a.id]
}

resource "aws_dax_parameter_group" "seed" {
  name = "${local.prefix}-dax"

  depends_on = [terraform_data.guard]
}
