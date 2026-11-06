#!/usr/bin/env bash
# Create the collector's customer-managed policies from the collector-policy-NN.json files beside this script and
# print their ARNs. For CloudFormation users: the documents together exceed CloudFormation's inline template limit,
# so create the policies with this script and attach them to the role by ARN (ManagedPolicyArns).
# Usage: ./create-collector-policies.sh [name-prefix]    (uses the AWS CLI's current profile and partition)
set -euo pipefail
prefix="${1:-tap-aws-core-collector}"
here="$(cd "$(dirname "$0")" && pwd)"
for f in "$here"/collector-policy-*.json; do
  n="$(basename "$f" .json)"; n="${n#collector-policy-}"
  aws iam create-policy --policy-name "${prefix}-${n}" --policy-document "file://${f}" --query 'Policy.Arn' --output text
done
