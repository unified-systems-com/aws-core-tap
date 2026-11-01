#!/usr/bin/env bash
# Write the Terraform AWS provider's schema (`terraform providers schema -json`) to a file, for tf_conformance.py.
#
#   terraform_dump.sh [-v PROVIDER_VERSION] OUTPUT_FILE
#
# This is the only step that runs Terraform, and the one bounded exception to the inert rule
# (specs/spec-aws-core-crosscheck.md, Inert Readers). It is built so the provider can reach no credential:
#
#   * it runs `init` and `providers schema` in an empty temporary directory, never plan or apply;
#   * `env -i` starts Terraform with an EMPTY environment (no AWS_*, no tokens, no TF_* variables, no CLI config),
#     plus only PATH, a throwaway HOME and TMPDIR, and proxy and certificate settings if the caller has them;
#   * HOME is a fresh empty directory, so ~/.aws, ~/.terraformrc and any credential helper do not exist for it;
#   * the provider is verified against the dependency lock file committed in terraform_locks/ (`-lockfile=readonly`),
#     so a binary whose checksum is not in that file is refused, whatever the registry serves. A version with no
#     committed lock file is refused: generate one with `terraform providers lock` in a throwaway directory and
#     review the hashes before committing it.
#
# The JSON is written with sorted keys; the provider version and the file's sha256 are printed so a run can be recorded.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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
lock="$here/terraform_locks/$version.lock.hcl"
[ -f "$lock" ] || { echo "no committed lock file for $version ($lock): refusing to run an unverified provider" >&2; exit 1; }

out_dir="$(cd "$(dirname "$1")" && pwd)"
out="$out_dir/$(basename "$1")"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/home" "$work/tmp"
cp "$lock" "$work/.terraform.lock.hcl"
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

# The only variables the provider process may see.
envargs=("PATH=$PATH" "HOME=$work/home" "TMPDIR=$work/tmp" "TF_IN_AUTOMATION=1" "TF_INPUT=0" "CHECKPOINT_DISABLE=1")
for v in HTTPS_PROXY HTTP_PROXY NO_PROXY https_proxy http_proxy no_proxy SSL_CERT_FILE SSL_CERT_DIR; do
  if [ -n "${!v:-}" ]; then envargs+=("$v=${!v}"); fi
done

(
  cd "$work"
  env -i "${envargs[@]}" terraform init -backend=false -input=false -no-color -lockfile=readonly >/dev/null
  env -i "${envargs[@]}" terraform providers schema -json >"$work/schema.raw.json"
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
echo "provider: hashicorp/aws $version (verified against terraform_locks/$version.lock.hcl)"
echo "file: $out"
echo "sha256: $digest"
