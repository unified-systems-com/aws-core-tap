#!/usr/bin/env bash
# Write the Terraform AWS provider's schema (`terraform providers schema -json`) to a file, for tf_conformance.py.
#
#   terraform_dump.sh [-v PROVIDER_VERSION] OUTPUT_FILE
#
# This is the only step that runs Terraform. It runs `init` and `providers schema` in an empty temporary
# directory, never plan or apply, with every AWS_* variable removed, so it needs and can use no credentials.
# `init` downloads the provider at exactly the pinned version and checks its signature. The JSON is written
# with sorted keys; the provider version and the file's sha256 are printed so a run can be recorded.
set -euo pipefail

version="6.71.0"
while getopts "v:" opt; do
  case "$opt" in
    v) version="$OPTARG" ;;
    *) echo "usage: $0 [-v PROVIDER_VERSION] OUTPUT_FILE" >&2; exit 2 ;;
  esac
done
shift $((OPTIND - 1))
if [ "$#" -ne 1 ]; then
  echo "usage: $0 [-v PROVIDER_VERSION] OUTPUT_FILE" >&2
  exit 2
fi
if ! [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "provider version must look like 6.71.0, got: $version" >&2
  exit 2
fi
command -v terraform >/dev/null || { echo "terraform is not installed" >&2; exit 1; }

out_dir="$(cd "$(dirname "$1")" && pwd)"
out="$out_dir/$(basename "$1")"

# No credentials, profiles or endpoints from the environment reach the provider.
while IFS='=' read -r name _; do
  case "$name" in
    AWS_*) unset "$name" ;;
  esac
done < <(env)

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cat >"$work/main.tf" <<EOF
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "= $version"
    }
  }
}
EOF

(
  cd "$work"
  export TF_IN_AUTOMATION=1 TF_INPUT=0 CHECKPOINT_DISABLE=1
  terraform init -backend=false -input=false -no-color >/dev/null
  terraform providers schema -json >"$work/schema.raw.json"
)

# Key-sorted, so the same provider gives the same bytes.
if command -v jq >/dev/null; then
  jq -S -c . "$work/schema.raw.json" >"$out"
else
  python3 -I -c 'import json,sys; json.dump(json.load(open(sys.argv[1])), sys.stdout, sort_keys=True, separators=(",", ":")); print()' "$work/schema.raw.json" >"$out"
fi

if command -v sha256sum >/dev/null; then
  digest="$(sha256sum "$out" | cut -d' ' -f1)"
else
  digest="$(shasum -a 256 "$out" | cut -d' ' -f1)"
fi
echo "provider: hashicorp/aws $version"
echo "file: $out"
echo "sha256: $digest"
