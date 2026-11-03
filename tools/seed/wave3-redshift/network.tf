data "aws_availability_zones" "available" {
  state = "available"
}

# A private network of its own: no internet gateway, no route out, nothing public. Three subnets in three zones,
# because a Redshift Serverless workgroup asks for three.
resource "aws_vpc" "seed" {
  cidr_block = "10.94.0.0/16"

  depends_on = [terraform_data.guard]
}

resource "aws_subnet" "a" {
  vpc_id            = aws_vpc.seed.id
  cidr_block        = "10.94.1.0/24"
  availability_zone = data.aws_availability_zones.available.names[0]
}

resource "aws_subnet" "b" {
  vpc_id            = aws_vpc.seed.id
  cidr_block        = "10.94.2.0/24"
  availability_zone = data.aws_availability_zones.available.names[1]
}

resource "aws_subnet" "c" {
  vpc_id            = aws_vpc.seed.id
  cidr_block        = "10.94.3.0/24"
  availability_zone = data.aws_availability_zones.available.names[2]
}

# One group for the cluster and the workgroup, with no rules at all.
resource "aws_security_group" "db" {
  name        = "${local.prefix}-db"
  description = "seed wave 3 redshift: cluster and workgroup group, no rules"
  vpc_id      = aws_vpc.seed.id
}
