data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "seed" {
  cidr_block = "10.99.0.0/16"

  depends_on = [terraform_data.guard]
}

resource "aws_subnet" "a" {
  vpc_id            = aws_vpc.seed.id
  cidr_block        = "10.99.1.0/24"
  availability_zone = data.aws_availability_zones.available.names[0]
}

resource "aws_subnet" "b" {
  vpc_id            = aws_vpc.seed.id
  cidr_block        = "10.99.2.0/24"
  availability_zone = data.aws_availability_zones.available.names[1]
}

resource "aws_internet_gateway" "seed" {
  vpc_id = aws_vpc.seed.id
}

resource "aws_route_table" "seed" {
  vpc_id = aws_vpc.seed.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.seed.id
  }
}

resource "aws_route_table_association" "a" {
  subnet_id      = aws_subnet.a.id
  route_table_id = aws_route_table.seed.id
}

resource "aws_network_acl" "seed" {
  vpc_id = aws_vpc.seed.id
}

# Awkward case, the public setting: a rule open to the world on a high port, with nothing attached to the group.
resource "aws_security_group" "open" {
  name        = "${local.prefix}-open"
  description = "seed wave 1: world-open high port, nothing attached"
  vpc_id      = aws_vpc.seed.id
}

resource "aws_vpc_security_group_ingress_rule" "open" {
  security_group_id = aws_security_group.open.id
  ip_protocol       = "tcp"
  from_port         = 49152
  to_port           = 49152
  cidr_ipv4         = "0.0.0.0/0"
  description       = "seed wave 1: public setting case"
}

resource "aws_security_group" "instance" {
  name        = "${local.prefix}-instance"
  description = "seed wave 1: instance group, no rules"
  vpc_id      = aws_vpc.seed.id
}
