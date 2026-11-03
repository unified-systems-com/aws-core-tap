data "aws_availability_zones" "available" {
  state = "available"
}

# A network of its own. The one node needs a way out (to register with the cluster's private endpoint it needs nothing
# more, but it pulls its images from ECR), so two subnets route to an internet gateway and give the node a public
# address; nothing is let in (the node's only group is the cluster group, which admits only itself). The two other
# subnets have no route out: the cluster's own interfaces sit there.
resource "aws_vpc" "seed" {
  cidr_block           = "10.95.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true # the cluster's private endpoint is resolved inside the VPC

  depends_on = [terraform_data.guard]
}

resource "aws_internet_gateway" "seed" {
  vpc_id = aws_vpc.seed.id
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.seed.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.seed.id
  }
}

# nosemgrep: terraform.aws.security.aws-subnet-has-public-ip-address.aws-subnet-has-public-ip-address
resource "aws_subnet" "public_a" {
  vpc_id                  = aws_vpc.seed.id
  cidr_block              = "10.95.1.0/24"
  availability_zone       = data.aws_availability_zones.available.names[0]
  map_public_ip_on_launch = true # NOSONAR: the node needs an address to reach ECR; its group admits no traffic from outside
}

# nosemgrep: terraform.aws.security.aws-subnet-has-public-ip-address.aws-subnet-has-public-ip-address
resource "aws_subnet" "public_b" {
  vpc_id                  = aws_vpc.seed.id
  cidr_block              = "10.95.2.0/24"
  availability_zone       = data.aws_availability_zones.available.names[1]
  map_public_ip_on_launch = true # NOSONAR: the node needs an address to reach ECR; its group admits no traffic from outside
}

resource "aws_route_table_association" "public_a" {
  subnet_id      = aws_subnet.public_a.id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "public_b" {
  subnet_id      = aws_subnet.public_b.id
  route_table_id = aws_route_table.public.id
}

# No association: these use the VPC's main route table, which has only the local route.
resource "aws_subnet" "private_a" {
  vpc_id            = aws_vpc.seed.id
  cidr_block        = "10.95.11.0/24"
  availability_zone = data.aws_availability_zones.available.names[0]
}

resource "aws_subnet" "private_b" {
  vpc_id            = aws_vpc.seed.id
  cidr_block        = "10.95.12.0/24"
  availability_zone = data.aws_availability_zones.available.names[1]
}
