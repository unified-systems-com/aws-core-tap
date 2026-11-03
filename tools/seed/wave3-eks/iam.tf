# The roles EKS requires, with the AWS managed policies EKS documents for each. No customer managed policy is declared
# here: the role catalog entry joins every attachment to a seeded policy, and an AWS managed policy is not seeded, so a
# policy of this module's own would leave the managed ones as unresolved edge targets.
locals {
  managed = "arn:${data.aws_partition.current.partition}:iam::aws:policy"
}

data "aws_iam_policy_document" "cluster_assume" {
  statement {
    actions = ["sts:AssumeRole", "sts:TagSession"]
    principals {
      type        = "Service"
      identifiers = ["eks.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "node_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "pod_assume" {
  statement {
    actions = ["sts:AssumeRole", "sts:TagSession"]
    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "cluster" {
  name               = "seed-w3e-${var.run_id}-cluster-role"
  assume_role_policy = data.aws_iam_policy_document.cluster_assume.json

  depends_on = [terraform_data.guard]
}

resource "aws_iam_role_policy_attachment" "cluster" {
  role       = aws_iam_role.cluster.name
  policy_arn = "${local.managed}/AmazonEKSClusterPolicy"
}

resource "aws_iam_role" "node" {
  name               = "seed-w3e-${var.run_id}-node-role"
  assume_role_policy = data.aws_iam_policy_document.node_assume.json

  depends_on = [terraform_data.guard]
}

resource "aws_iam_role_policy_attachment" "node" {
  for_each = toset(["AmazonEKSWorkerNodePolicy", "AmazonEKS_CNI_Policy", "AmazonEC2ContainerRegistryReadOnly"])

  role       = aws_iam_role.node.name
  policy_arn = "${local.managed}/${each.key}"
}

# The pod identity association's role: trusted by the pod identity service, granted nothing.
resource "aws_iam_role" "pod" {
  name               = "seed-w3e-${var.run_id}-pod-role"
  assume_role_policy = data.aws_iam_policy_document.pod_assume.json

  depends_on = [terraform_data.guard]
}

# The access entry's principal: a role nobody but EC2 may assume, granted nothing, and given no access policy in the
# cluster.
resource "aws_iam_role" "viewer" {
  name               = "seed-w3e-${var.run_id}-viewer-role"
  assume_role_policy = data.aws_iam_policy_document.node_assume.json

  depends_on = [terraform_data.guard]
}
