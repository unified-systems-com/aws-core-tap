# Wave 3b, edge services: API Gateway (REST and HTTP), Cognito, Route 53 and WAF Classic. Free while idle (a classic rule is billed
# by the month, prorated; the cost note prices it). Nothing is invoked, no user is created.

# --- Cognito ---

resource "aws_cognito_user_pool" "seed" {
  name                = "${local.prefix}-pool"
  deletion_protection = "INACTIVE"

  depends_on = [terraform_data.guard]
}

resource "aws_cognito_user_pool_client" "seed" {
  name            = "${local.prefix}-client"
  user_pool_id    = aws_cognito_user_pool.seed.id
  generate_secret = false
}

resource "aws_cognito_user_pool_domain" "seed" {
  domain       = "${local.prefix}-domain"
  user_pool_id = aws_cognito_user_pool.seed.id
}

resource "aws_cognito_user_group" "seed" {
  name         = "${local.prefix}-group"
  user_pool_id = aws_cognito_user_pool.seed.id
  precedence   = 1
}

resource "aws_cognito_resource_server" "seed" {
  identifier   = "https://seed.example.invalid/${var.run_id}"
  name         = "${local.prefix}-resource-server"
  user_pool_id = aws_cognito_user_pool.seed.id

  scope {
    scope_name        = "read"
    scope_description = "read"
  }
}

resource "aws_cognito_identity_pool" "seed" {
  identity_pool_name               = "${local.prefix}-identity"
  allow_unauthenticated_identities = false

  depends_on = [terraform_data.guard]
}

# --- API Gateway, REST: one API with a mock integration, a stage, a usage plan, a key and a client certificate ---

resource "aws_api_gateway_rest_api" "seed" {
  name = "${local.prefix}-rest"

  # The default execute-api address is switched off, so the mock method cannot be called by anyone.
  disable_execute_api_endpoint = true

  endpoint_configuration {
    types = ["REGIONAL"]
  }

  body = jsonencode({
    openapi = "3.0.1"
    info    = { title = "seed", version = "1" }
    paths = {
      "/" = {
        get = {
          responses = { "200" = { description = "ok" } }
          x-amazon-apigateway-integration = {
            type                = "MOCK"
            requestTemplates    = { "application/json" = "{\"statusCode\": 200}" }
            passthroughBehavior = "never"
            responses           = { default = { statusCode = "200" } }
          }
        }
      }
    }
  })

  depends_on = [terraform_data.guard]
}

resource "aws_api_gateway_deployment" "seed" {
  rest_api_id = aws_api_gateway_rest_api.seed.id

  triggers = {
    redeploy = sha1(aws_api_gateway_rest_api.seed.body)
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "seed" { # NOSONAR: never invoked (the default address is off), so there is nothing to log, and access logs need an account-level role
  rest_api_id   = aws_api_gateway_rest_api.seed.id
  deployment_id = aws_api_gateway_deployment.seed.id
  stage_name    = "seed"

  xray_tracing_enabled = true
}

resource "aws_api_gateway_authorizer" "seed" {
  name            = "${local.prefix}-authorizer"
  rest_api_id     = aws_api_gateway_rest_api.seed.id
  type            = "COGNITO_USER_POOLS"
  provider_arns   = [aws_cognito_user_pool.seed.arn]
  identity_source = "method.request.header.Authorization"
}

resource "aws_api_gateway_api_key" "seed" {
  name = "${local.prefix}-key"
}

resource "aws_api_gateway_usage_plan" "seed" {
  name = "${local.prefix}-plan"

  api_stages {
    api_id = aws_api_gateway_rest_api.seed.id
    stage  = aws_api_gateway_stage.seed.stage_name
  }

  quota_settings {
    limit  = 1000
    period = "DAY"
  }

  throttle_settings {
    burst_limit = 10
    rate_limit  = 5
  }
}

resource "aws_api_gateway_client_certificate" "seed" {
  description = "${local.prefix} client certificate"
}

# --- API Gateway, HTTP: an API with no route and no integration ---

resource "aws_apigatewayv2_api" "seed" {
  name          = "${local.prefix}-http"
  protocol_type = "HTTP"

  disable_execute_api_endpoint = true

  depends_on = [terraform_data.guard]
}

# --- Route 53: a private zone (GovCloud has no public zones), a health check, a CIDR collection and a traffic policy ---

resource "aws_vpc" "seed" {
  cidr_block = "10.94.0.0/16"

  depends_on = [terraform_data.guard]
}

resource "aws_route53_zone" "seed" {
  name = "${local.prefix}.example.invalid"

  vpc {
    vpc_id = aws_vpc.seed.id
  }
}

resource "aws_route53_health_check" "seed" {
  type              = "TCP"
  fqdn              = "seed-health.example.invalid"
  port              = 443
  request_interval  = 30
  failure_threshold = 3
  disabled          = true
}

resource "aws_route53_cidr_collection" "seed" {
  name = "${local.prefix}-cidr"
}

resource "aws_route53_traffic_policy" "seed" {
  name = "${local.prefix}-policy"

  document = jsonencode({
    AWSPolicyFormatVersion = "2015-10-01"
    RecordType             = "A"
    StartEndpoint          = "endpoint-start-seed"
    Endpoints              = { "endpoint-start-seed" = { Type = "value", Value = "192.0.2.1" } }
  })
}

# --- WAF Classic: every match set and rule type (a web ACL can no longer be created: Classic is closed to new web ACLs) ---

resource "aws_wafregional_ipset" "seed" {
  name = "${local.prefix}-ipset"

  ip_set_descriptor {
    type  = "IPV4"
    value = "192.0.2.0/24"
  }

  depends_on = [terraform_data.guard]
}

resource "aws_wafregional_byte_match_set" "seed" {
  name = "${local.prefix}-bytematch"

  byte_match_tuples {
    text_transformation   = "NONE"
    target_string         = "seed"
    positional_constraint = "CONTAINS"

    field_to_match {
      type = "URI"
    }
  }
}

resource "aws_wafregional_geo_match_set" "seed" {
  name = "${local.prefix}-geomatch"

  geo_match_constraint {
    type  = "Country"
    value = "US"
  }
}

resource "aws_wafregional_regex_pattern_set" "seed" {
  name                  = "${local.prefix}-regex"
  regex_pattern_strings = ["seed[0-9]+"]
}

resource "aws_wafregional_size_constraint_set" "seed" {
  name = "${local.prefix}-size"

  size_constraints {
    text_transformation = "NONE"
    comparison_operator = "GT"
    size                = 4096

    field_to_match {
      type = "BODY"
    }
  }
}

resource "aws_wafregional_sql_injection_match_set" "seed" {
  name = "${local.prefix}-sqli"

  sql_injection_match_tuple {
    text_transformation = "URL_DECODE"

    field_to_match {
      type = "QUERY_STRING"
    }
  }
}

resource "aws_wafregional_xss_match_set" "seed" {
  name = "${local.prefix}-xss"

  xss_match_tuple {
    text_transformation = "URL_DECODE"

    field_to_match {
      type = "QUERY_STRING"
    }
  }
}

resource "aws_wafregional_rule" "seed" {
  name        = "${local.prefix}-rule"
  metric_name = "seedrule${var.run_id}"

  predicate {
    data_id = aws_wafregional_ipset.seed.id
    negated = false
    type    = "IPMatch"
  }
}

resource "aws_wafregional_rate_based_rule" "seed" {
  name        = "${local.prefix}-rate"
  metric_name = "seedrate${var.run_id}"
  rate_key    = "IP"
  rate_limit  = 2000

  predicate {
    data_id = aws_wafregional_ipset.seed.id
    negated = false
    type    = "IPMatch"
  }
}
