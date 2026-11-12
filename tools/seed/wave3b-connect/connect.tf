# Wave 3b, Amazon Connect: an instance with SAML identity management (so no password is ever needed), hours of operation, a queue, a
# quick connect, a routing profile, a security profile, a user, a user hierarchy group, a contact flow and a flow module. An instance
# bills by use (calls, chats, agent minutes), and none occurs; no phone number is claimed. Creating the first instance in an account
# makes the service-linked role AWSServiceRoleForAmazonConnect, which a destroy leaves behind.

resource "aws_connect_instance" "seed" {
  identity_management_type = "SAML"
  instance_alias           = local.prefix
  inbound_calls_enabled    = false
  outbound_calls_enabled   = false

  depends_on = [terraform_data.guard]
}

resource "aws_connect_hours_of_operation" "seed" {
  instance_id = aws_connect_instance.seed.id
  name        = "${local.prefix}-hours"
  time_zone   = "UTC"

  config {
    day = "MONDAY"

    start_time {
      hours   = 9
      minutes = 0
    }

    end_time {
      hours   = 17
      minutes = 0
    }
  }
}

resource "aws_connect_queue" "seed" {
  instance_id           = aws_connect_instance.seed.id
  name                  = "${local.prefix}-queue"
  hours_of_operation_id = aws_connect_hours_of_operation.seed.hours_of_operation_id
}

resource "aws_connect_quick_connect" "seed" {
  instance_id = aws_connect_instance.seed.id
  name        = "${local.prefix}-quick"

  quick_connect_config {
    quick_connect_type = "PHONE_NUMBER"

    phone_config {
      phone_number = "+15555550100"
    }
  }
}

resource "aws_connect_routing_profile" "seed" {
  instance_id               = aws_connect_instance.seed.id
  name                      = "${local.prefix}-routing"
  description               = "seed"
  default_outbound_queue_id = aws_connect_queue.seed.queue_id

  media_concurrencies {
    channel     = "VOICE"
    concurrency = 1
  }
}

resource "aws_connect_security_profile" "seed" {
  instance_id = aws_connect_instance.seed.id
  name        = "${local.prefix}-security"
  description = "seed"
}

resource "aws_connect_user" "seed" {
  instance_id          = aws_connect_instance.seed.id
  name                 = "seed${var.run_id}"
  routing_profile_id   = aws_connect_routing_profile.seed.routing_profile_id
  security_profile_ids = [aws_connect_security_profile.seed.security_profile_id]

  identity_info {
    first_name = "Seed"
    last_name  = "User"
  }

  phone_config {
    phone_type = "SOFT_PHONE"
  }
}

resource "aws_connect_user_hierarchy_structure" "seed" {
  instance_id = aws_connect_instance.seed.id

  hierarchy_structure {
    level_one {
      name = "seed"
    }
  }
}

resource "aws_connect_user_hierarchy_group" "seed" {
  instance_id = aws_connect_instance.seed.id
  name        = "${local.prefix}-group"

  depends_on = [aws_connect_user_hierarchy_structure.seed]
}

resource "aws_connect_contact_flow" "seed" {
  instance_id = aws_connect_instance.seed.id
  name        = "${local.prefix}-flow"
  type        = "CONTACT_FLOW"

  content = jsonencode({
    Version     = "2019-10-30"
    StartAction = "end"
    Actions = [{
      Identifier  = "end"
      Type        = "DisconnectParticipant"
      Parameters  = {}
      Transitions = {}
    }]
  })
}

resource "aws_connect_contact_flow_module" "seed" {
  instance_id = aws_connect_instance.seed.id
  name        = "${local.prefix}-module"

  content = jsonencode({
    Version     = "2019-10-30"
    StartAction = "end"
    Metadata    = {}
    Actions = [{
      Identifier  = "end"
      Type        = "DisconnectParticipant"
      Parameters  = {}
      Transitions = {}
    }]
    Settings = {
      InputParameters  = []
      OutputParameters = []
      Transitions      = [{ DisplayName = "Success", ReferenceName = "Success", Description = "" }]
    }
  })
}
