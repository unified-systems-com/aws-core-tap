data "aws_availability_zones" "available" {
  state = "available"
}

# A private network of its own with one subnet and no way out.
resource "aws_vpc" "seed" {
  cidr_block = "10.95.0.0/16"

  depends_on = [terraform_data.guard]
}

resource "aws_subnet" "a" {
  vpc_id            = aws_vpc.seed.id
  cidr_block        = "10.95.1.0/24"
  availability_zone = data.aws_availability_zones.available.names[0]
}

resource "aws_security_group" "seed" {
  name        = "${local.prefix}-sg"
  description = "seed wave 1b: group carrying one ingress and one egress rule"
  vpc_id      = aws_vpc.seed.id
}

# The two rule types, on a documentation-range address; nothing is attached to the group.
resource "aws_vpc_security_group_ingress_rule" "seed" {
  security_group_id = aws_security_group.seed.id
  ip_protocol       = "tcp"
  from_port         = 8443
  to_port           = 8443
  cidr_ipv4         = "192.0.2.0/24"
  description       = "seed wave 1b: ingress rule"
}

resource "aws_vpc_security_group_egress_rule" "seed" {
  security_group_id = aws_security_group.seed.id
  ip_protocol       = "tcp"
  from_port         = 8443
  to_port           = 8443
  cidr_ipv4         = "192.0.2.0/24"
  description       = "seed wave 1b: egress rule"
}

resource "aws_network_interface" "seed" {
  subnet_id       = aws_subnet.a.id
  security_groups = [aws_security_group.seed.id]
  description     = "seed wave 1b: unattached interface"
}

# Flow logs to a bucket of their own; the service attaches its own delivery policy to it.
resource "aws_flow_log" "seed" {
  vpc_id               = aws_vpc.seed.id
  traffic_type         = "ALL"
  log_destination_type = "s3"
  log_destination      = aws_s3_bucket.flow.arn
}
