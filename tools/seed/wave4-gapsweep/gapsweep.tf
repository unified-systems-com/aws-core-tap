# Wave 4, the gap sweep: one small private stack that gives every edge added in the gap sweep something to link. A VPC with two
# subnets; a security group and a rule that names another group; an instance with an EBS volume and a network interface; an
# Auto Scaling group and its launch template; an internal network and application load balancer with a listener and a target
# group each; a private Route 53 zone with alias records to both; and a Memcached cluster in a cache subnet group. Nothing is
# reachable (no internet gateway, no route out). The hourly charges are the instance, the two load balancers and the cache
# node; `cost.md` prices them. Destroy it as soon as the comparison has run.

data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

resource "aws_vpc" "seed" {
  cidr_block           = "10.96.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  depends_on = [terraform_data.guard]
}

resource "aws_subnet" "a" {
  vpc_id            = aws_vpc.seed.id
  cidr_block        = "10.96.1.0/24"
  availability_zone = data.aws_availability_zones.available.names[0]
}

resource "aws_subnet" "b" {
  vpc_id            = aws_vpc.seed.id
  cidr_block        = "10.96.2.0/24"
  availability_zone = data.aws_availability_zones.available.names[1]
}

# Two groups; the second one's rule names the first (REFERENCES_SECURITY_GROUP).
resource "aws_security_group" "front" {
  name        = "${local.prefix}-front"
  description = "seed wave 4: referenced group"
  vpc_id      = aws_vpc.seed.id
}

resource "aws_security_group" "back" {
  name        = "${local.prefix}-back"
  description = "seed wave 4: group whose rule names the front group"
  vpc_id      = aws_vpc.seed.id
}

resource "aws_vpc_security_group_ingress_rule" "from_front" {
  security_group_id            = aws_security_group.back.id
  referenced_security_group_id = aws_security_group.front.id
  ip_protocol                  = "tcp"
  from_port                    = 8080
  to_port                      = 8080
}

# --- compute: an instance, a volume on it, a network interface of its own ---

resource "aws_instance" "seed" {
  ami                         = data.aws_ssm_parameter.al2023.value
  instance_type               = "t3.nano"
  subnet_id                   = aws_subnet.a.id
  vpc_security_group_ids      = [aws_security_group.back.id]
  associate_public_ip_address = false

  metadata_options {
    http_tokens = "required"
  }
}

resource "aws_ebs_volume" "seed" {
  availability_zone = aws_subnet.a.availability_zone
  size              = 1
  type              = "gp3"
  encrypted         = true
}

resource "aws_volume_attachment" "seed" {
  device_name = "/dev/sdf"
  volume_id   = aws_ebs_volume.seed.id
  instance_id = aws_instance.seed.id
}

resource "aws_network_interface" "extra" {
  subnet_id       = aws_subnet.a.id
  security_groups = [aws_security_group.back.id]
}

resource "aws_network_interface_attachment" "extra" {
  instance_id          = aws_instance.seed.id
  network_interface_id = aws_network_interface.extra.id
  device_index         = 1
}

resource "aws_launch_template" "seed" {
  name          = "${local.prefix}-lt"
  image_id      = data.aws_ssm_parameter.al2023.value
  instance_type = "t3.nano"

  network_interfaces {
    associate_public_ip_address = false
    security_groups             = [aws_security_group.back.id]
  }

  metadata_options {
    http_tokens = "required"
  }
}

resource "aws_autoscaling_group" "seed" {
  name                = "${local.prefix}-asg"
  min_size            = 1
  max_size            = 1
  desired_capacity    = 1
  vpc_zone_identifier = [aws_subnet.b.id]

  launch_template {
    id      = aws_launch_template.seed.id
    version = "$Latest"
  }
}

# --- load balancers: one network, one application, each with a target group holding the instance ---

resource "aws_lb" "network" { # NOSONAR: internal, no traffic, run-scoped and destroyed within the hour; there is nothing to log
  name               = "${local.prefix}-nlb"
  load_balancer_type = "network"
  internal           = true
  subnets            = [aws_subnet.a.id, aws_subnet.b.id]
}

resource "aws_lb_target_group" "network" {
  name        = "${local.prefix}-nt"
  port        = 8080
  protocol    = "TCP"
  vpc_id      = aws_vpc.seed.id
  target_type = "instance"
}

resource "aws_lb_target_group_attachment" "network" {
  target_group_arn = aws_lb_target_group.network.arn
  target_id        = aws_instance.seed.id
}

resource "aws_lb_listener" "network" {
  load_balancer_arn = aws_lb.network.arn
  port              = 8080
  protocol          = "TCP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.network.arn
  }
}

resource "aws_lb" "application" { # NOSONAR: internal, no traffic, run-scoped and destroyed within the hour; there is nothing to log
  name               = "${local.prefix}-alb"
  load_balancer_type = "application"
  internal           = true
  subnets            = [aws_subnet.a.id, aws_subnet.b.id]
  security_groups    = [aws_security_group.front.id]
}

resource "aws_lb_target_group" "application" {
  name        = "${local.prefix}-at"
  port        = 8080
  protocol    = "HTTP"
  vpc_id      = aws_vpc.seed.id
  target_type = "instance"
}

resource "aws_lb_target_group_attachment" "application" {
  target_group_arn = aws_lb_target_group.application.arn
  target_id        = aws_instance.seed.id
}

resource "aws_lb_listener" "application" { # NOSONAR: internal listener on a load balancer nothing can reach, destroyed within the hour
  load_balancer_arn = aws_lb.application.arn
  port              = 80
  protocol          = "HTTP" # NOSONAR: see the resource line

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.application.arn
  }
}

# --- Route 53: a private zone whose aliases name both load balancers ---

resource "aws_route53_zone" "seed" {
  name = "${local.prefix}.seed.internal"

  vpc {
    vpc_id = aws_vpc.seed.id
  }
}

resource "aws_route53_record" "to_network" {
  zone_id = aws_route53_zone.seed.zone_id
  name    = "net.${aws_route53_zone.seed.name}"
  type    = "A"

  alias {
    name                   = aws_lb.network.dns_name
    zone_id                = aws_lb.network.zone_id
    evaluate_target_health = false
  }
}

resource "aws_route53_record" "to_application" {
  zone_id = aws_route53_zone.seed.zone_id
  name    = "app.${aws_route53_zone.seed.name}"
  type    = "A"

  alias {
    name                   = aws_lb.application.dns_name
    zone_id                = aws_lb.application.zone_id
    evaluate_target_health = false
  }
}

# --- ElastiCache: a cluster in a cache subnet group (USES_CACHE_SUBNET_GROUP, then the group's subnets) ---

resource "aws_elasticache_subnet_group" "seed" {
  name       = "${local.prefix}-cache"
  subnet_ids = [aws_subnet.a.id, aws_subnet.b.id]
}

resource "aws_elasticache_cluster" "seed" {
  cluster_id         = "w4g-${var.run_id}"
  engine             = "memcached"
  node_type          = "cache.t4g.micro"
  num_cache_nodes    = 1
  subnet_group_name  = aws_elasticache_subnet_group.seed.name
  security_group_ids = [aws_security_group.back.id]
}
