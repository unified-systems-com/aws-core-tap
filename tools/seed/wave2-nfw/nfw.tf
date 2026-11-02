# A stateless rule group with one pass rule on a documentation-range address; nothing is routed through the firewall.
resource "aws_networkfirewall_rule_group" "seed" {
  name     = "${local.prefix}-rules"
  type     = "STATELESS"
  capacity = 10

  rule_group {
    rules_source {
      stateless_rules_and_custom_actions {
        stateless_rule {
          priority = 1
          rule_definition {
            actions = ["aws:pass"]
            match_attributes {
              source {
                address_definition = "192.0.2.1/32"
              }
              destination {
                address_definition = "192.0.2.2/32"
              }
              protocols = [6]
            }
          }
        }
      }
    }
  }

  depends_on = [terraform_data.guard]
}

resource "aws_networkfirewall_firewall_policy" "seed" {
  name = "${local.prefix}-policy"

  firewall_policy {
    stateless_default_actions          = ["aws:forward_to_sfe"]
    stateless_fragment_default_actions = ["aws:forward_to_sfe"]

    stateless_rule_group_reference {
      priority     = 1
      resource_arn = aws_networkfirewall_rule_group.seed.arn
    }
  }
}

# The costly resource: one endpoint, billed by the hour. The wave destroys it as soon as the check has run.
resource "aws_networkfirewall_firewall" "seed" {
  name                              = "${local.prefix}-fw"
  firewall_policy_arn               = aws_networkfirewall_firewall_policy.seed.arn
  vpc_id                            = aws_vpc.fw.id
  delete_protection                 = false
  subnet_change_protection          = false
  firewall_policy_change_protection = false

  subnet_mapping {
    subnet_id = aws_subnet.fw.id
  }
}

resource "aws_networkfirewall_vpc_endpoint_association" "seed" {
  firewall_arn = aws_networkfirewall_firewall.seed.arn
  vpc_id       = aws_vpc.client.id

  subnet_mapping {
    subnet_id = aws_subnet.client.id
  }
}
