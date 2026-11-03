# Wave 3b, compute and network: ECS, EFS, load balancers, VPC endpoints and Transit Gateway. Everything is private (internal
# load balancers, no internet gateway, no route out). The hourly charges are the two load balancers and the two Transit
# Gateway attachments; the cost note prices them. Nothing is invoked, no task runs, no instance launches.

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "seed" {
  cidr_block = "10.95.0.0/16"

  depends_on = [terraform_data.guard]
}

resource "aws_subnet" "a" {
  vpc_id            = aws_vpc.seed.id
  cidr_block        = "10.95.1.0/24"
  availability_zone = data.aws_availability_zones.available.names[0]
}

resource "aws_subnet" "b" {
  vpc_id            = aws_vpc.seed.id
  cidr_block        = "10.95.2.0/24"
  availability_zone = data.aws_availability_zones.available.names[1]
}

# One group with no rules at all.
resource "aws_security_group" "seed" {
  name        = "${local.prefix}-sg"
  description = "seed wave 3b compute: no rules"
  vpc_id      = aws_vpc.seed.id
}

# --- ECS: a cluster, a task definition and a service that is told to run no task ---

resource "aws_ecs_cluster" "seed" {
  name = "${local.prefix}-cluster"

  depends_on = [terraform_data.guard]
}

resource "aws_ecs_task_definition" "seed" {
  family                   = "${local.prefix}-task"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512

  container_definitions = jsonencode([{
    name      = "seed"
    image     = "public.ecr.aws/docker/library/busybox:latest"
    essential = true
    command   = ["true"]
  }])
}

resource "aws_ecs_service" "seed" {
  name            = "${local.prefix}-service"
  cluster         = aws_ecs_cluster.seed.arn
  task_definition = aws_ecs_task_definition.seed.arn
  desired_count   = 0
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = [aws_subnet.a.id]
    security_groups  = [aws_security_group.seed.id]
    assign_public_ip = false
  }
}

# --- EFS: a file system, a mount target and an access point (empty; storage is billed by use) ---

# An empty file system that lives for under an hour, with the AWS managed key: a key of its own would add a costed resource.
# nosemgrep: terraform.aws.security.aws-efs-filesystem-encrypted-with-cmk.aws-efs-filesystem-encrypted-with-cmk
resource "aws_efs_file_system" "seed" {
  creation_token = "${local.prefix}-efs"
  encrypted      = true

  depends_on = [terraform_data.guard]
}

resource "aws_efs_mount_target" "seed" {
  file_system_id  = aws_efs_file_system.seed.id
  subnet_id       = aws_subnet.a.id
  security_groups = [aws_security_group.seed.id]
}

resource "aws_efs_access_point" "seed" {
  file_system_id = aws_efs_file_system.seed.id

  posix_user {
    gid = 1000
    uid = 1000
  }

  root_directory {
    path = "/seed"

    creation_info {
      owner_gid   = 1000
      owner_uid   = 1000
      permissions = "0755"
    }
  }
}

# --- Elastic Load Balancing: an internal application balancer with a target group, a listener and a rule; a classic one ---

resource "aws_lb" "app" { # NOSONAR: internal, no traffic ever reaches it, and access logs need a bucket with a service policy
  name               = substr("${local.prefix}-alb", 0, 32)
  internal           = true
  load_balancer_type = "application"
  subnets            = [aws_subnet.a.id, aws_subnet.b.id]
  security_groups    = [aws_security_group.seed.id]

  enable_deletion_protection = false

  depends_on = [terraform_data.guard]
}

resource "aws_lb_target_group" "seed" {
  name        = substr("${local.prefix}-tg", 0, 32)
  port        = 80
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.seed.id

  health_check {
    path = "/"
  }
}

resource "aws_lb_listener" "seed" {
  load_balancer_arn = aws_lb.app.arn
  port              = 80
  # nosemgrep: terraform.aws.security.insecure-load-balancer-tls-version.insecure-load-balancer-tls-version
  protocol = "HTTP" # NOSONAR: an internal listener that answers a fixed response; nothing can reach it

  default_action {
    type = "fixed-response"

    fixed_response {
      content_type = "text/plain"
      message_body = "seed"
      status_code  = "200"
    }
  }
}

resource "aws_lb_listener_rule" "seed" {
  listener_arn = aws_lb_listener.seed.arn
  priority     = 10

  action {
    type = "fixed-response"

    fixed_response {
      content_type = "text/plain"
      message_body = "seed rule"
      status_code  = "200"
    }
  }

  condition {
    path_pattern {
      values = ["/seed"]
    }
  }
}

resource "aws_elb" "classic" { # NOSONAR: internal, no traffic ever reaches it, and access logs need a bucket with a service policy
  name            = substr("${local.prefix}-elb", 0, 32)
  internal        = true
  subnets         = [aws_subnet.a.id, aws_subnet.b.id]
  security_groups = [aws_security_group.seed.id]

  listener {
    instance_port     = 80
    instance_protocol = "tcp"
    lb_port           = 80
    lb_protocol       = "tcp"
  }

  depends_on = [terraform_data.guard]
}

# --- VPC endpoints: a gateway endpoint to S3 (free) ---

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.seed.id
  service_name      = "com.amazonaws.${data.aws_region.current.region}.s3"
  vpc_endpoint_type = "Gateway"
}

# --- Transit Gateway: a gateway, a route table, a VPC attachment, a connect attachment over it, and a multicast domain ---

resource "aws_ec2_transit_gateway" "seed" {
  description       = "${local.prefix} transit gateway"
  multicast_support = "enable"

  auto_accept_shared_attachments  = "disable"
  default_route_table_association = "enable"
  default_route_table_propagation = "enable"

  depends_on = [terraform_data.guard]
}

resource "aws_ec2_transit_gateway_route_table" "seed" {
  transit_gateway_id = aws_ec2_transit_gateway.seed.id
}

resource "aws_ec2_transit_gateway_vpc_attachment" "seed" {
  transit_gateway_id = aws_ec2_transit_gateway.seed.id
  vpc_id             = aws_vpc.seed.id
  subnet_ids         = [aws_subnet.a.id]
}

resource "aws_ec2_transit_gateway_connect" "seed" {
  transport_attachment_id = aws_ec2_transit_gateway_vpc_attachment.seed.id
  transit_gateway_id      = aws_ec2_transit_gateway.seed.id
  protocol                = "gre"
}

resource "aws_ec2_transit_gateway_multicast_domain" "seed" {
  transit_gateway_id = aws_ec2_transit_gateway.seed.id
}
