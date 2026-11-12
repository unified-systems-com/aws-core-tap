data "aws_availability_zones" "available" {
  state = "available"
}

# A private network of its own: no internet gateway, no route out, nothing public. The caches are not reachable.
resource "aws_vpc" "seed" {
  cidr_block = "10.93.0.0/16"

  depends_on = [terraform_data.guard]
}

resource "aws_subnet" "a" {
  vpc_id            = aws_vpc.seed.id
  cidr_block        = "10.93.1.0/24"
  availability_zone = data.aws_availability_zones.available.names[0]
}

resource "aws_subnet" "b" {
  vpc_id            = aws_vpc.seed.id
  cidr_block        = "10.93.2.0/24"
  availability_zone = data.aws_availability_zones.available.names[1]
}

# One group for every cache, with no rules at all.
resource "aws_security_group" "cache" {
  name        = "${local.prefix}-cache"
  description = "seed wave 3 elasticache: cache group, no rules"
  vpc_id      = aws_vpc.seed.id
}
