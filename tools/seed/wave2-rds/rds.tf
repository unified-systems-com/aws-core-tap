resource "aws_db_subnet_group" "seed" {
  name       = "${local.prefix}-subnets"
  subnet_ids = [aws_subnet.a.id, aws_subnet.b.id]

  depends_on = [terraform_data.guard]
}

resource "aws_db_parameter_group" "seed" {
  name   = "${local.prefix}-pg"
  family = "postgres17"

  depends_on = [terraform_data.guard]
}

resource "aws_db_option_group" "seed" {
  name                     = "${local.prefix}-og"
  engine_name              = "mysql"
  major_engine_version     = "8.0"
  option_group_description = "seed wave 2 rds: option group with no options"

  depends_on = [terraform_data.guard]
}

resource "aws_rds_cluster_parameter_group" "seed" {
  name   = "${local.prefix}-cpg"
  family = "aurora-postgresql17"

  depends_on = [terraform_data.guard]
}

# Carries no message: the subscription is never triggered, and the topic is destroyed with the wave.
resource "aws_sns_topic" "events" { # NOSONAR
  name = "${local.prefix}-events"

  depends_on = [terraform_data.guard]
}

resource "aws_db_event_subscription" "seed" {
  name        = "${local.prefix}-events"
  sns_topic   = aws_sns_topic.events.arn
  source_type = "db-instance"
  enabled     = true
}

# A small instance with no public address, a RDS-managed master secret (no password in the state or the repository),
# and no final snapshot: it is destroyed with the wave. No log export: it is never connected to, so it writes no log, and
# an export would add log groups to be destroyed.
# nosemgrep: terraform.aws.security.aws-db-instance-no-logging.aws-db-instance-no-logging
resource "aws_db_instance" "seed" {
  identifier                  = "${local.prefix}-db"
  engine                      = "postgres"
  engine_version              = "17.11"
  instance_class              = "db.t4g.micro"
  allocated_storage           = 20
  storage_type                = "gp2"
  storage_encrypted           = true
  username                    = "seedadmin"
  manage_master_user_password = true
  db_subnet_group_name        = aws_db_subnet_group.seed.name
  vpc_security_group_ids      = [aws_security_group.db.id]
  parameter_group_name        = aws_db_parameter_group.seed.name
  publicly_accessible         = false
  multi_az                    = false
  backup_retention_period     = 1 # NOSONAR: the shortest that keeps snapshots possible; the instance lives under an hour
  skip_final_snapshot         = true
  deletion_protection         = false
  apply_immediately           = true
  auto_minor_version_upgrade  = false
}

resource "aws_db_snapshot" "seed" {
  db_instance_identifier = aws_db_instance.seed.identifier
  db_snapshot_identifier = "${local.prefix}-snap"
}

# Serverless v2 at its smallest capacity: one writer, no reader.
resource "aws_rds_cluster" "seed" {
  cluster_identifier              = "${local.prefix}-cluster"
  engine                          = "aurora-postgresql"
  engine_version                  = "17.11"
  engine_mode                     = "provisioned"
  master_username                 = "seedadmin"
  manage_master_user_password     = true
  db_subnet_group_name            = aws_db_subnet_group.seed.name
  vpc_security_group_ids          = [aws_security_group.db.id]
  db_cluster_parameter_group_name = aws_rds_cluster_parameter_group.seed.name
  storage_encrypted               = true
  backup_retention_period         = 1 # NOSONAR: the shortest that keeps snapshots possible; the cluster lives under an hour
  skip_final_snapshot             = true
  deletion_protection             = false
  apply_immediately               = true

  serverlessv2_scaling_configuration {
    min_capacity = 0.5
    max_capacity = 1
  }
}

resource "aws_rds_cluster_instance" "seed" {
  identifier           = "${local.prefix}-cluster-writer"
  cluster_identifier   = aws_rds_cluster.seed.id
  instance_class       = "db.serverless"
  engine               = aws_rds_cluster.seed.engine
  engine_version       = aws_rds_cluster.seed.engine_version
  db_subnet_group_name = aws_db_subnet_group.seed.name
  publicly_accessible  = false
}

resource "aws_rds_cluster_endpoint" "seed" {
  cluster_identifier          = aws_rds_cluster.seed.id
  cluster_endpoint_identifier = "${local.prefix}-endpoint"
  custom_endpoint_type        = "ANY"
  static_members              = [aws_rds_cluster_instance.seed.id]
}

resource "aws_db_cluster_snapshot" "seed" {
  db_cluster_identifier          = aws_rds_cluster.seed.id
  db_cluster_snapshot_identifier = "${local.prefix}-csnap"

  depends_on = [aws_rds_cluster_instance.seed]
}

# The container of a global database, with no cluster in it.
resource "aws_rds_global_cluster" "seed" {
  global_cluster_identifier = "${local.prefix}-global"
  engine                    = "aurora-postgresql"
  engine_version            = "17.11"
  storage_encrypted         = true
  deletion_protection       = false

  depends_on = [terraform_data.guard]
}

resource "aws_db_proxy" "seed" {
  name                   = "${local.prefix}-proxy"
  engine_family          = "POSTGRESQL"
  role_arn               = aws_iam_role.proxy.arn
  vpc_subnet_ids         = [aws_subnet.a.id, aws_subnet.b.id]
  vpc_security_group_ids = [aws_security_group.db.id]
  require_tls            = true
  idle_client_timeout    = 1800

  auth {
    auth_scheme = "SECRETS"
    iam_auth    = "DISABLED"
    secret_arn  = aws_db_instance.seed.master_user_secret[0].secret_arn
  }

  depends_on = [aws_iam_role_policy_attachment.proxy]
}

resource "aws_db_proxy_default_target_group" "seed" {
  db_proxy_name = aws_db_proxy.seed.name

  connection_pool_config {
    max_connections_percent = 100
  }
}

resource "aws_db_proxy_target" "seed" {
  db_proxy_name          = aws_db_proxy.seed.name
  target_group_name      = aws_db_proxy_default_target_group.seed.name
  db_instance_identifier = aws_db_instance.seed.identifier
}

resource "aws_db_proxy_endpoint" "seed" {
  db_proxy_name          = aws_db_proxy.seed.name
  db_proxy_endpoint_name = "${local.prefix}-proxy-endpoint"
  vpc_subnet_ids         = [aws_subnet.a.id, aws_subnet.b.id]
  vpc_security_group_ids = [aws_security_group.db.id]
  target_role            = "READ_WRITE"

  depends_on = [aws_db_proxy_target.seed]
}
