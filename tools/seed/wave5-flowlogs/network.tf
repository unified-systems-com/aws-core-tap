# Wave 5, flow logs (aws-core-tap#218): a private VPC where one instance calls another on known ports, so that flow logs,
# the summarising query and its filters have traffic to show. The client calls the server on 8080 and 9090 (allowed) and
# 9443 (not allowed by the security group, so those records are REJECT). Nothing is reachable from outside: no internet
# gateway, no NAT, no route out. The hourly charges are the two instances; `cost.md` prices the rest.

data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

resource "aws_vpc" "seed" {
  cidr_block           = "10.95.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  depends_on = [terraform_data.guard]
}

resource "aws_subnet" "a" {
  vpc_id            = aws_vpc.seed.id
  cidr_block        = "10.95.1.0/24"
  availability_zone = data.aws_availability_zones.available.names[0]
}

resource "aws_security_group" "traffic" {
  name        = "${local.prefix}-traffic"
  description = "seed wave 5: 8080 and 9090 allowed inside the VPC; 9443 deliberately not"
  vpc_id      = aws_vpc.seed.id
}

resource "aws_vpc_security_group_ingress_rule" "web" {
  for_each          = toset(["8080", "9090"])
  security_group_id = aws_security_group.traffic.id
  cidr_ipv4         = aws_vpc.seed.cidr_block
  ip_protocol       = "tcp"
  from_port         = tonumber(each.value)
  to_port           = tonumber(each.value)
}

resource "aws_vpc_security_group_egress_rule" "inside" {
  security_group_id = aws_security_group.traffic.id
  cidr_ipv4         = aws_vpc.seed.cidr_block
  ip_protocol       = "-1"
}

resource "aws_instance" "server" {
  ami                         = data.aws_ssm_parameter.al2023.value
  instance_type               = "t3.nano"
  subnet_id                   = aws_subnet.a.id
  vpc_security_group_ids      = [aws_security_group.traffic.id]
  associate_public_ip_address = false
  user_data                   = <<-EOT
    #!/bin/bash
    mkdir -p /srv/a /srv/b
    cd /srv/a && nohup python3 -m http.server 8080 >/dev/null 2>&1 &
    cd /srv/b && nohup python3 -m http.server 9090 >/dev/null 2>&1 &
  EOT

  metadata_options {
    http_tokens = "required"
  }

  tags = { Name = "${local.prefix}-server" }
}

resource "aws_instance" "client" {
  ami                         = data.aws_ssm_parameter.al2023.value
  instance_type               = "t3.nano"
  subnet_id                   = aws_subnet.a.id
  vpc_security_group_ids      = [aws_security_group.traffic.id]
  associate_public_ip_address = false
  user_data                   = <<-EOT
    #!/bin/bash
    cat > /usr/local/bin/seed-traffic <<'LOOP'
    #!/bin/bash
    while true; do
      for port in 8080 9090 9443; do curl -s -o /dev/null -m 3 "http://${aws_instance.server.private_ip}:$port/"; done
      sleep 20
    done
    LOOP
    chmod +x /usr/local/bin/seed-traffic
    nohup /usr/local/bin/seed-traffic >/dev/null 2>&1 &
  EOT

  metadata_options {
    http_tokens = "required"
  }

  tags = { Name = "${local.prefix}-client" }
}
