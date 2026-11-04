# Wave 3b, EC2 and VPC extras: a key pair, a placement group, a managed prefix list, DHCP options, an egress-only internet gateway,
# a customer gateway, a VPN gateway with a VPN connection, a peering between two VPCs, a launch template, a traffic mirror filter
# with a rule, a network insights path, and a NAT gateway with its Elastic IP. The hourly charges are the NAT gateway
# and the VPN connection; the cost note prices them. No instance launches, no traffic flows, and no analysis is started.

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "seed" {
  cidr_block = "10.97.0.0/16"

  depends_on = [terraform_data.guard]
}

resource "aws_vpc" "peer" {
  cidr_block = "10.98.0.0/16"

  depends_on = [terraform_data.guard]
}

resource "aws_subnet" "a" {
  vpc_id            = aws_vpc.seed.id
  cidr_block        = "10.97.1.0/24"
  availability_zone = data.aws_availability_zones.available.names[0]
}

# --- Plain EC2 objects ---

# A public key made for the purpose; the private half was discarded at once.
resource "aws_key_pair" "seed" {
  key_name   = "${local.prefix}-key"
  public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHNYQ167LQfhmVx7WeLdB0wbcdlTVrh9v4vVOThRQ/to seed"

  depends_on = [terraform_data.guard]
}

resource "aws_placement_group" "seed" {
  name     = "${local.prefix}-pg"
  strategy = "cluster"

  depends_on = [terraform_data.guard]
}

resource "aws_ec2_managed_prefix_list" "seed" {
  name           = "${local.prefix}-prefix"
  address_family = "IPv4"
  max_entries    = 2

  entry {
    cidr        = "192.0.2.0/24"
    description = "documentation range"
  }

  depends_on = [terraform_data.guard]
}

resource "aws_vpc_dhcp_options" "seed" {
  domain_name         = "${local.prefix}.example.invalid"
  domain_name_servers = ["AmazonProvidedDNS"]

  depends_on = [terraform_data.guard]
}

resource "aws_egress_only_internet_gateway" "seed" {
  vpc_id = aws_vpc.seed.id
}

resource "aws_launch_template" "seed" {
  name          = "${local.prefix}-lt"
  instance_type = "t3.micro"

  depends_on = [terraform_data.guard]
}

# --- VPN: a customer gateway at an address that is only recorded (the documentation ranges are refused; nothing connects), a virtual private gateway and the connection between them ---

resource "aws_customer_gateway" "seed" {
  bgp_asn    = 65000
  ip_address = "8.8.8.8"
  type       = "ipsec.1"

  depends_on = [terraform_data.guard]
}

resource "aws_vpn_gateway" "seed" {
  vpc_id = aws_vpc.seed.id
}

resource "aws_vpn_connection" "seed" {
  customer_gateway_id = aws_customer_gateway.seed.id
  vpn_gateway_id      = aws_vpn_gateway.seed.id
  type                = "ipsec.1"
  static_routes_only  = true
}

# --- Peering between the two VPCs of this module, accepted in place ---

resource "aws_vpc_peering_connection" "seed" {
  vpc_id      = aws_vpc.seed.id
  peer_vpc_id = aws_vpc.peer.id
  auto_accept = true
}

# --- Traffic mirroring: a filter with one rule (a target needs an interface attached to an instance) ---

resource "aws_network_interface" "a" {
  subnet_id = aws_subnet.a.id
}

resource "aws_network_interface" "b" {
  subnet_id = aws_subnet.a.id
}

resource "aws_ec2_traffic_mirror_filter" "seed" {
  description      = "${local.prefix} filter"
  network_services = ["amazon-dns"]

  depends_on = [terraform_data.guard]
}

resource "aws_ec2_traffic_mirror_filter_rule" "seed" {
  traffic_mirror_filter_id = aws_ec2_traffic_mirror_filter.seed.id
  destination_cidr_block   = "10.97.0.0/16"
  source_cidr_block        = "10.97.0.0/16"
  rule_number              = 1
  rule_action              = "accept"
  traffic_direction        = "ingress"
}

# --- Reachability Analyzer: a path between the two interfaces; no analysis is started ---

resource "aws_ec2_network_insights_path" "seed" {
  source      = aws_network_interface.a.id
  destination = aws_network_interface.b.id
  protocol    = "tcp"
}

# --- NAT gateway and its Elastic IP ---

resource "aws_internet_gateway" "seed" {
  vpc_id = aws_vpc.seed.id
}

resource "aws_eip" "seed" {
  domain = "vpc"

  depends_on = [terraform_data.guard]
}

resource "aws_nat_gateway" "seed" {
  allocation_id = aws_eip.seed.id
  subnet_id     = aws_subnet.a.id

  depends_on = [aws_internet_gateway.seed]
}
