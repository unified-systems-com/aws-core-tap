resource "aws_elasticache_subnet_group" "seed" {
  name       = "${local.prefix}-subnets"
  subnet_ids = [aws_subnet.a.id, aws_subnet.b.id]

  depends_on = [terraform_data.guard]
}

resource "aws_elasticache_parameter_group" "seed" {
  name   = "${local.prefix}-pg"
  family = "valkey8"

  depends_on = [terraform_data.guard]
}

# One Valkey node, encrypted at rest and in transit, no snapshots kept, no final snapshot (none is named).
resource "aws_elasticache_replication_group" "seed" {
  replication_group_id       = "${local.prefix}-rg"
  description                = "seed wave 3 elasticache: one-node Valkey group"
  engine                     = "valkey"
  engine_version             = "8.0"
  node_type                  = "cache.t4g.micro"
  num_cache_clusters         = 1
  parameter_group_name       = aws_elasticache_parameter_group.seed.name
  subnet_group_name          = aws_elasticache_subnet_group.seed.name
  security_group_ids         = [aws_security_group.cache.id]
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  automatic_failover_enabled = false
  multi_az_enabled           = false
  snapshot_retention_limit   = 0 # NOSONAR: no backups for a cache that holds no data and lives under two hours
  auto_minor_version_upgrade = false
  apply_immediately          = true
}

# A standalone cache cluster. Valkey cannot be created through the cache cluster API (only through a replication
# group), so this one runs Redis OSS, the smallest node, one per cluster.
resource "aws_elasticache_cluster" "seed" {
  cluster_id                 = "${local.prefix}-std"
  engine                     = "redis"
  engine_version             = "7.1"
  node_type                  = "cache.t4g.micro"
  num_cache_nodes            = 1
  parameter_group_name       = "default.redis7"
  subnet_group_name          = aws_elasticache_subnet_group.seed.name
  security_group_ids         = [aws_security_group.cache.id]
  snapshot_retention_limit   = 0 # NOSONAR: no backups for a cache that holds no data and lives under two hours
  auto_minor_version_upgrade = false
  apply_immediately          = true

  depends_on = [terraform_data.guard]
}

# Users that can do nothing (access string "off", every command denied). Valkey requires an authentication mode, and
# IAM needs no secret; with IAM the user name equals the user id. Valkey groups do not require a user named "default".
resource "aws_elasticache_user" "a" {
  user_id       = "${local.prefix}-ua"
  user_name     = "${local.prefix}-ua"
  engine        = "valkey"
  access_string = "off -@all"

  authentication_mode {
    type = "iam"
  }

  depends_on = [terraform_data.guard]
}

resource "aws_elasticache_user" "b" {
  user_id       = "${local.prefix}-ub"
  user_name     = "${local.prefix}-ub"
  engine        = "valkey"
  access_string = "off -@all"

  authentication_mode {
    type = "iam"
  }

  depends_on = [terraform_data.guard]
}

# A user group attached to no cache.
resource "aws_elasticache_user_group" "seed" {
  user_group_id = "${local.prefix}-users"
  engine        = "valkey"
  user_ids      = [aws_elasticache_user.a.user_id, aws_elasticache_user.b.user_id]
}

# Serverless Valkey at its smallest limits: 1 GB of data, 1000 ECPU per second. Billed on the 100 MB minimum.
resource "aws_elasticache_serverless_cache" "seed" {
  name                     = "${local.prefix}-sl"
  engine                   = "valkey"
  major_engine_version     = "8"
  description              = "seed wave 3 elasticache: smallest serverless Valkey cache"
  subnet_ids               = [aws_subnet.a.id, aws_subnet.b.id]
  security_group_ids       = [aws_security_group.cache.id]
  snapshot_retention_limit = 0 # NOSONAR: no backups for a cache that holds no data and lives under two hours

  cache_usage_limits {
    data_storage {
      maximum = 1
      unit    = "GB"
    }
    ecpu_per_second {
      maximum = 1000
    }
  }

  depends_on = [terraform_data.guard]
}
