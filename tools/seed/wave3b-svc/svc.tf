# Wave 3b, service definitions: IoT Core, SES v2, Rekognition and Transcribe. Everything here is a
# definition: no message is published, no email is sent, no image is analysed and no
# audio is transcribed. All of it is free while idle.

# --- IoT Core: groups, a thing type, a policy, a topic rule that republishes, a role alias and a provisioning template ---

data "aws_iam_policy_document" "iot_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["iot.amazonaws.com", "credentials.iot.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "iot" {
  name               = "seed-w3s-${var.run_id}-iot-role"
  assume_role_policy = data.aws_iam_policy_document.iot_assume.json

  depends_on = [terraform_data.guard]
}

resource "aws_iot_thing_group" "seed" {
  name = "${local.prefix}-group"

  depends_on = [terraform_data.guard]
}

resource "aws_iot_billing_group" "seed" {
  name = "${local.prefix}-billing"

  depends_on = [terraform_data.guard]
}

resource "aws_iot_thing_type" "seed" {
  name = "${local.prefix}-type"

  depends_on = [terraform_data.guard]
}

# Allows nothing to connect: the only statement denies every action.
resource "aws_iot_policy" "seed" {
  name = "${local.prefix}-policy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Deny"
      Action   = ["iot:Connect"]
      Resource = ["*"]
    }]
  })

  depends_on = [terraform_data.guard]
}

resource "aws_iot_topic_rule" "seed" {
  name        = replace("${local.prefix}-rule", "-", "_")
  enabled     = false
  sql         = "SELECT * FROM 'seed/none'"
  sql_version = "2016-03-23"

  republish {
    role_arn = aws_iam_role.iot.arn
    topic    = "seed/out"
  }

  depends_on = [terraform_data.guard]
}

resource "aws_iot_role_alias" "seed" {
  alias    = "${local.prefix}-alias"
  role_arn = aws_iam_role.iot.arn
}

resource "aws_iot_provisioning_template" "seed" {
  name                  = "${local.prefix}-template"
  provisioning_role_arn = aws_iam_role.iot.arn
  enabled               = false

  template_body = jsonencode({
    Parameters = { SerialNumber = { Type = "String" } }
    Resources = {
      thing = {
        Type       = "AWS::IoT::Thing"
        Properties = { ThingName = { Ref = "SerialNumber" } }
      }
      certificate = {
        Type       = "AWS::IoT::Certificate"
        Properties = { CertificateId = { Ref = "AWS::IoT::Certificate::Id" }, Status = "Active" }
      }
    }
  })

  depends_on = [terraform_data.guard]
}

# --- SES v2: a configuration set, a contact list, a domain identity that is never verified, and a standard IP pool ---

resource "aws_sesv2_configuration_set" "seed" {
  configuration_set_name = "${local.prefix}-set"

  depends_on = [terraform_data.guard]
}

resource "aws_sesv2_contact_list" "seed" {
  contact_list_name = "${local.prefix}-list"

  depends_on = [terraform_data.guard]
}

resource "aws_sesv2_email_identity" "seed" {
  email_identity = "${local.prefix}.example.invalid"

  depends_on = [terraform_data.guard]
}

resource "aws_sesv2_dedicated_ip_pool" "seed" {
  pool_name    = "${local.prefix}-pool"
  scaling_mode = "STANDARD"

  depends_on = [terraform_data.guard]
}

# --- Rekognition and Transcribe: an empty face collection, a vocabulary and a vocabulary filter ---

resource "aws_rekognition_collection" "seed" {
  collection_id = "${local.prefix}-faces"

  depends_on = [terraform_data.guard]
}

resource "aws_transcribe_vocabulary" "seed" {
  vocabulary_name = "${local.prefix}-vocabulary"
  language_code   = "en-US"
  phrases         = ["seed", "wave"]

  depends_on = [terraform_data.guard]
}

resource "aws_transcribe_vocabulary_filter" "seed" {
  vocabulary_filter_name = "${local.prefix}-filter"
  language_code          = "en-US"
  words                  = ["seedword"]

  depends_on = [terraform_data.guard]
}
