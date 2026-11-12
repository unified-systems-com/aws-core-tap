# The costly resource: one control plane, billed by the hour. Kubernetes 1.34, the oldest version still in standard
# support on 2026-11-02; the STANDARD upgrade policy keeps it from moving onto extended support ($0.50 an hour more).
# The API endpoint is private only; access is by access entries (API mode), and the identity running Terraform is not
# made a cluster admin. No control plane logging: nothing is run on the cluster, and logging would add log groups to be
# destroyed. No envelope encryption of Kubernetes secrets: the cluster holds none of its own.
resource "aws_eks_cluster" "seed" { # NOSONAR: no control plane logging or secrets key; holds nothing, destroyed within two hours
  name     = "${local.prefix}-cluster"
  role_arn = aws_iam_role.cluster.arn
  version  = "1.34"

  vpc_config {
    subnet_ids              = [aws_subnet.private_a.id, aws_subnet.private_b.id]
    endpoint_private_access = true
    endpoint_public_access  = false
  }

  access_config {
    authentication_mode                         = "API"
    bootstrap_cluster_creator_admin_permissions = false
  }

  upgrade_policy {
    support_type = "STANDARD"
  }

  depends_on = [aws_iam_role_policy_attachment.cluster]
}

# One on-demand t3.medium node in a public subnet (see network.tf), Amazon Linux 2023.
resource "aws_eks_node_group" "seed" {
  cluster_name    = aws_eks_cluster.seed.name
  node_group_name = "${local.prefix}-nodes"
  node_role_arn   = aws_iam_role.node.arn
  subnet_ids      = [aws_subnet.public_a.id, aws_subnet.public_b.id]
  ami_type        = "AL2023_x86_64_STANDARD"
  capacity_type   = "ON_DEMAND"
  instance_types  = ["t3.medium"]
  disk_size       = 20

  scaling_config {
    desired_size = 1
    min_size     = 1
    max_size     = 1
  }

  depends_on = [aws_iam_role_policy_attachment.node, aws_route_table_association.public_a, aws_route_table_association.public_b]
}

# The agent that serves pod identity associations; a DaemonSet on the one node.
resource "aws_eks_addon" "seed" {
  cluster_name = aws_eks_cluster.seed.name
  addon_name   = "eks-pod-identity-agent"

  depends_on = [aws_eks_node_group.seed]
}

# The viewer role may authenticate to the cluster and is bound to nothing: no access policy, no group.
resource "aws_eks_access_entry" "seed" {
  cluster_name  = aws_eks_cluster.seed.name
  principal_arn = aws_iam_role.viewer.arn
  type          = "STANDARD"
}

resource "aws_eks_pod_identity_association" "seed" {
  cluster_name    = aws_eks_cluster.seed.name
  namespace       = "seed"
  service_account = "seed"
  role_arn        = aws_iam_role.pod.arn
}

# An OIDC identity provider for the cluster's API server. The issuer is a reserved documentation domain (RFC 2606): it
# serves no discovery document, so no token from it can ever be verified. Associating it updates the control plane
# (15 to 30 minutes), so it waits for everything else, and the cluster accepts no other change while it runs.
resource "aws_eks_identity_provider_config" "seed" {
  cluster_name = aws_eks_cluster.seed.name

  oidc {
    identity_provider_config_name = "${local.prefix}-oidc"
    issuer_url                    = "https://oidc.example.com"
    client_id                     = "seed-w3e"
  }

  depends_on = [
    aws_eks_node_group.seed,
    aws_eks_addon.seed,
    aws_eks_access_entry.seed,
    aws_eks_pod_identity_association.seed,
  ]
}
