# The edge path (aws-core-tap#218, Q14): traffic through an internet gateway, a load balancer and a gateway endpoint,
# so the summary shows the hard cases the two-instance trial does not. Off unless `edge_path = true`; everything here
# has `count = local.path`.
#
#   visitor (public subnet, public IP) --internet--> internet gateway --> ALB (two public subnets) --> server:8080,
#   and /b/* --> server:9090; server --> DynamoDB through a gateway endpoint (put-item every 20 s).
#
# The visitor reaches the load balancer by its public DNS name, so its traffic leaves through the internet gateway and
# comes back in: flow logs see a public address talking to the load balancer's nodes. The load balancer admits only the
# visitor's own public address. The server has no route out; its one way to DynamoDB is the endpoint.

locals {
  path = var.edge_path ? 1 : 0
}

resource "aws_internet_gateway" "path" {
  count  = local.path
  vpc_id = aws_vpc.seed.id
}

resource "aws_subnet" "public" {
  count                   = var.edge_path ? 2 : 0
  vpc_id                  = aws_vpc.seed.id
  cidr_block              = "10.95.${10 + count.index}.0/24"
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = false
}

resource "aws_route_table" "public" {
  count  = local.path
  vpc_id = aws_vpc.seed.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.path[0].id
  }
}

resource "aws_route_table_association" "public" {
  count          = var.edge_path ? 2 : 0
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public[0].id
}

# The private subnet's own route table, so the gateway endpoint's route lands on it and nowhere else.
resource "aws_route_table" "private" {
  count  = local.path
  vpc_id = aws_vpc.seed.id
}

resource "aws_route_table_association" "private" {
  count          = local.path
  subnet_id      = aws_subnet.a.id
  route_table_id = aws_route_table.private[0].id
}

# --- the visitor: the "internet" side ---

resource "aws_security_group" "visitor" {
  count       = local.path
  name        = "${local.prefix}-visitor"
  description = "seed wave 5 edge path: the visitor calls the load balancer on 80 over the internet"
  vpc_id      = aws_vpc.seed.id
}

resource "aws_vpc_security_group_egress_rule" "visitor_http" {
  count             = local.path
  security_group_id = aws_security_group.visitor[0].id
  cidr_ipv4         = "0.0.0.0/0" # the load balancer's public addresses, which change; port 80 only
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
}

# nosemgrep: terraform.aws.security.aws-ec2-has-public-ip.aws-ec2-has-public-ip
resource "aws_instance" "visitor" {
  count                       = local.path
  ami                         = data.aws_ssm_parameter.al2023.value
  instance_type               = "t3.nano"
  subnet_id                   = aws_subnet.public[0].id
  vpc_security_group_ids      = [aws_security_group.visitor[0].id]
  associate_public_ip_address = true # NOSONAR: the visitor must reach the load balancer over the internet; it accepts no inbound and lives under an hour
  user_data                   = <<-EOT
    #!/bin/bash
    cat > /usr/local/bin/seed-visit <<'LOOP'
    #!/bin/bash
    while true; do
      for path in / /b/; do curl -s -o /dev/null -m 5 "http://${aws_lb.path[0].dns_name}$path"; done
      sleep 20
    done
    LOOP
    chmod +x /usr/local/bin/seed-visit
    nohup /usr/local/bin/seed-visit >/dev/null 2>&1 &
  EOT

  metadata_options {
    http_tokens = "required"
  }

  tags = { Name = "${local.prefix}-visitor" }
}

# --- the load balancer ---

resource "aws_security_group" "alb" {
  count       = local.path
  name        = "${local.prefix}-alb"
  description = "seed wave 5 edge path: 80 from the visitor public address only, out to the server"
  vpc_id      = aws_vpc.seed.id
}

resource "aws_vpc_security_group_ingress_rule" "alb_from_visitor" {
  count             = local.path
  security_group_id = aws_security_group.alb[0].id
  cidr_ipv4         = "${aws_instance.visitor[0].public_ip}/32"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
}

resource "aws_vpc_security_group_egress_rule" "alb_to_server" {
  for_each          = var.edge_path ? toset(["8080", "9090"]) : toset([])
  security_group_id = aws_security_group.alb[0].id
  cidr_ipv4         = aws_vpc.seed.cidr_block
  ip_protocol       = "tcp"
  from_port         = tonumber(each.key)
  to_port           = tonumber(each.key)
}

resource "aws_lb" "path" { # NOSONAR: admits only the visitor's /32, run-scoped and destroyed within the hour; flow logs are the record this trial reads
  count              = local.path
  name               = "${local.prefix}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb[0].id]
  subnets            = aws_subnet.public[*].id

  depends_on = [aws_route_table_association.public]
}

resource "aws_lb_target_group" "path" {
  for_each    = var.edge_path ? { a = 8080, b = 9090 } : {}
  name        = "${local.prefix}-${each.key}"
  port        = each.value
  protocol    = "HTTP"
  target_type = "instance"
  vpc_id      = aws_vpc.seed.id

  health_check {
    path    = "/"
    matcher = "200-404"
  }
}

resource "aws_lb_target_group_attachment" "path" {
  for_each         = aws_lb_target_group.path
  target_group_arn = each.value.arn
  target_id        = aws_instance.server.id
  port             = each.value.port
}

resource "aws_lb_listener" "path" {
  count             = local.path
  load_balancer_arn = aws_lb.path[0].arn
  port              = 80
  # nosemgrep: terraform.aws.security.insecure-load-balancer-tls-version.insecure-load-balancer-tls-version
  protocol = "HTTP" # NOSONAR: plain HTTP so the trial needs no certificate; only the visitor's /32 can reach it, and it carries no data

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.path["a"].arn
  }
}

resource "aws_lb_listener_rule" "b" {
  count        = local.path
  listener_arn = aws_lb_listener.path[0].arn
  priority     = 10

  condition {
    path_pattern {
      values = ["/b/*"]
    }
  }

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.path["b"].arn
  }
}

# --- DynamoDB through a gateway endpoint ---

# nosemgrep: terraform.aws.security.aws-dynamodb-table-unencrypted.aws-dynamodb-table-unencrypted
resource "aws_dynamodb_table" "path" { # encrypted at rest by default with an AWS-owned key; holds only ping timestamps
  count        = local.path
  name         = "${local.prefix}-pings"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"

  attribute {
    name = "id"
    type = "S"
  }

  depends_on = [terraform_data.guard]
}

resource "aws_vpc_endpoint" "dynamodb" {
  count             = local.path
  vpc_id            = aws_vpc.seed.id
  service_name      = "com.amazonaws.${data.aws_region.current.region}.dynamodb"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private[0].id]
}

# The server's one way out: HTTPS to DynamoDB's own prefix list, which only the endpoint routes.
resource "aws_vpc_security_group_egress_rule" "server_dynamodb" {
  count             = local.path
  security_group_id = aws_security_group.traffic.id
  prefix_list_id    = aws_vpc_endpoint.dynamodb[0].prefix_list_id
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

data "aws_iam_policy_document" "server_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "server" {
  count              = local.path
  name               = "seed-w5f-${var.run_id}-server"
  assume_role_policy = data.aws_iam_policy_document.server_trust.json

  depends_on = [terraform_data.guard]
}

resource "aws_iam_role_policy" "server" {
  count = local.path
  name  = "${local.prefix}-server"
  role  = aws_iam_role.server[0].id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["dynamodb:PutItem"], Resource = aws_dynamodb_table.path[0].arn }]
  })
}

resource "aws_iam_instance_profile" "server" {
  count = local.path
  name  = "seed-w5f-${var.run_id}-server"
  role  = aws_iam_role.server[0].name

  depends_on = [terraform_data.guard]
}
