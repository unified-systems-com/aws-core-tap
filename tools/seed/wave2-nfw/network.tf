data "aws_availability_zones" "available" {
  state = "available"
}

# Two private networks and no way out of either: the firewall's own, and one to hold a second endpoint of it.
resource "aws_vpc" "fw" {
  cidr_block = "10.97.0.0/16"

  depends_on = [terraform_data.guard]
}

resource "aws_subnet" "fw" {
  vpc_id            = aws_vpc.fw.id
  cidr_block        = "10.97.1.0/24"
  availability_zone = data.aws_availability_zones.available.names[0]
}

resource "aws_vpc" "client" {
  cidr_block = "10.96.0.0/16"

  depends_on = [terraform_data.guard]
}

resource "aws_subnet" "client" {
  vpc_id            = aws_vpc.client.id
  cidr_block        = "10.96.1.0/24"
  availability_zone = data.aws_availability_zones.available.names[0]
}
