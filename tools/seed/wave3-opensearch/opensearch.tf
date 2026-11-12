# The costly resource: one t3.small.search node with 10 GiB of gp2, in one private subnet. Encrypted at rest and node to
# node, HTTPS only. Fine-grained access control is off and no access policy is set: no resource policy grants the data
# plane to anyone, and the subnet has no route in or out. No log publishing: nothing is indexed or searched, and
# publishing would add log groups to be destroyed.
resource "aws_opensearch_domain" "seed" { # NOSONAR: no log publishing or access policy; holds no data, destroyed within two hours
  domain_name    = "${local.prefix}-os"
  engine_version = "OpenSearch_2.19"

  cluster_config {
    instance_type            = "t3.small.search"
    instance_count           = 1
    zone_awareness_enabled   = false
    dedicated_master_enabled = false
  }

  ebs_options {
    ebs_enabled = true
    volume_type = "gp2"
    volume_size = 10
  }

  vpc_options {
    subnet_ids         = [aws_subnet.a.id]
    security_group_ids = [aws_security_group.domain.id]
  }

  encrypt_at_rest {
    enabled = true
  }

  node_to_node_encryption {
    enabled = true
  }

  domain_endpoint_options {
    enforce_https       = true
    tls_security_policy = "Policy-Min-TLS-1-2-2019-07"
  }

  advanced_security_options {
    enabled = false
  }

  depends_on = [terraform_data.guard]
}
