data "aws_availability_zones" "available" {
  state = "available"
}

# A private network of its own: no internet gateway, no route out, nothing public. The domain is not reachable.
resource "aws_vpc" "seed" {
  cidr_block = "10.92.0.0/16"

  depends_on = [terraform_data.guard]
}

resource "aws_subnet" "a" {
  vpc_id            = aws_vpc.seed.id
  cidr_block        = "10.92.1.0/24"
  availability_zone = data.aws_availability_zones.available.names[0]
}

# One group for the domain, with no rules at all.
resource "aws_security_group" "domain" {
  name        = "${local.prefix}-domain"
  description = "seed wave 3 opensearch: domain group, no rules"
  vpc_id      = aws_vpc.seed.id
}
