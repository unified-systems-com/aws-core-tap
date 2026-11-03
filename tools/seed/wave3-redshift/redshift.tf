resource "aws_redshift_subnet_group" "seed" {
  name       = "${local.prefix}-subnets"
  subnet_ids = [aws_subnet.a.id, aws_subnet.b.id, aws_subnet.c.id]

  depends_on = [terraform_data.guard]
}

resource "aws_redshift_parameter_group" "seed" {
  name   = "${local.prefix}-pg"
  family = "redshift-2.0"

  depends_on = [terraform_data.guard]
}

# The costly resource: one ra3.large node, billed by the hour. No public address, a Redshift-managed master secret (no
# password in the state or the repository), no final snapshot: it is destroyed with the wave. No audit logging: it is
# never connected to, and logging would add a bucket or log groups to be destroyed.
resource "aws_redshift_cluster" "seed" { # NOSONAR: no audit logging; never connected to, destroyed within two hours
  cluster_identifier                  = "${local.prefix}-cluster"
  node_type                           = "ra3.large"
  cluster_type                        = "single-node"
  master_username                     = "seedadmin"
  manage_master_password              = true
  cluster_subnet_group_name           = aws_redshift_subnet_group.seed.name
  cluster_parameter_group_name        = aws_redshift_parameter_group.seed.name
  vpc_security_group_ids              = [aws_security_group.db.id]
  publicly_accessible                 = false
  encrypted                           = true
  automated_snapshot_retention_period = 1 # NOSONAR: the shortest that keeps snapshots possible; the cluster lives under two hours
  skip_final_snapshot                 = true
  apply_immediately                   = true
  allow_version_upgrade               = false
}

# A manual snapshot of an empty cluster; destroyed with the wave.
resource "aws_redshift_cluster_snapshot" "seed" {
  cluster_identifier  = aws_redshift_cluster.seed.cluster_identifier
  snapshot_identifier = "${local.prefix}-snap"
}

# A schedule attached to nothing: it never takes a snapshot.
resource "aws_redshift_snapshot_schedule" "seed" {
  identifier  = "${local.prefix}-schedule"
  description = "seed wave 3 redshift: schedule attached to no cluster"
  definitions = ["rate(12 hours)"]

  depends_on = [terraform_data.guard]
}

# A limit on a feature the wave never uses (Spectrum scans), which only logs if breached.
resource "aws_redshift_usage_limit" "seed" {
  cluster_identifier = aws_redshift_cluster.seed.id
  feature_type       = "spectrum"
  limit_type         = "data-scanned"
  amount             = 1
  period             = "daily"
  breach_action      = "log"
}

# A pause of the seed cluster, disabled, on a date that does not come round during the run.
resource "aws_redshift_scheduled_action" "seed" {
  name        = "${local.prefix}-pause"
  description = "seed wave 3 redshift: disabled pause of the seed cluster"
  schedule    = "cron(0 3 1 1 ? 2099)"
  iam_role    = aws_iam_role.scheduler.arn
  enable      = false

  target_action {
    pause_cluster {
      cluster_identifier = aws_redshift_cluster.seed.cluster_identifier
    }
  }

  depends_on = [aws_iam_role_policy_attachment.scheduler]
}

# Carries no message: the subscription is never triggered, and the topic is destroyed with the wave.
resource "aws_sns_topic" "events" { # NOSONAR
  name = "${local.prefix}-events"

  depends_on = [terraform_data.guard]
}

resource "aws_redshift_event_subscription" "seed" {
  name          = "${local.prefix}-events"
  sns_topic_arn = aws_sns_topic.events.arn
  source_type   = "cluster"
  severity      = "ERROR"
  enabled       = true
}

# The key a snapshot copy grant names; scheduled for deletion (7 days) by the destroy, like wave 1's.
resource "aws_kms_key" "grant" {
  description             = "${local.prefix} snapshot copy grant key"
  deletion_window_in_days = 7
  enable_key_rotation     = true

  depends_on = [terraform_data.guard]
}

resource "aws_redshift_snapshot_copy_grant" "seed" {
  snapshot_copy_grant_name = "${local.prefix}-grant"
  kms_key_id               = aws_kms_key.grant.arn
}

# Redshift Serverless: a namespace with no admin user and a workgroup at the smallest base capacity. No query is run,
# so no compute is billed.
resource "aws_redshiftserverless_namespace" "seed" {
  namespace_name = "${local.prefix}-ns"

  depends_on = [terraform_data.guard]
}

resource "aws_redshiftserverless_workgroup" "seed" {
  namespace_name      = aws_redshiftserverless_namespace.seed.namespace_name
  workgroup_name      = "${local.prefix}-wg"
  base_capacity       = 8
  publicly_accessible = false
  subnet_ids          = [aws_subnet.a.id, aws_subnet.b.id, aws_subnet.c.id]
  security_group_ids  = [aws_security_group.db.id]
}
