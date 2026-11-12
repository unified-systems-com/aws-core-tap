data "aws_availability_zones" "available" {
  state = "available"
}

# A private network of its own: no internet gateway, no route out, nothing public. The databases are not reachable.
resource "aws_vpc" "seed" {
  cidr_block = "10.98.0.0/16"

  depends_on = [terraform_data.guard]
}

resource "aws_subnet" "a" {
  vpc_id            = aws_vpc.seed.id
  cidr_block        = "10.98.1.0/24"
  availability_zone = data.aws_availability_zones.available.names[0]
}

resource "aws_subnet" "b" {
  vpc_id            = aws_vpc.seed.id
  cidr_block        = "10.98.2.0/24"
  availability_zone = data.aws_availability_zones.available.names[1]
}

# One group for the databases and the proxy, with no rules at all.
resource "aws_security_group" "db" {
  name        = "${local.prefix}-db"
  description = "seed wave 2 rds: database and proxy group, no rules"
  vpc_id      = aws_vpc.seed.id
}
