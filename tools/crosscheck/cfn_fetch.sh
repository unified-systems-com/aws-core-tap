#!/usr/bin/env bash
# Download AWS's per-region CloudFormation resource specifications into a directory.
#
#   cfn_fetch.sh <directory>
#
# Public files, no credentials. Each file is fetched once; nothing is retried or looped over. A line per file is
# written to <directory>/manifest.tsv: file, URL, HTTP status, sha256, bytes, ResourceSpecificationVersion.
# The verifier (cfn_verifier.py) only reads what this leaves behind.
set -euo pipefail

if [[ "$#" -ne 1 ]]; then
  echo "usage: $0 <directory>" >&2
  exit 2
fi
dest="$1"
mkdir -p "$dest"

# region|URL; the commercial address is the one the "Resource specification" documentation page lists for us-east-1.
sources=(
  "us-gov-west-1|https://s3.us-gov-west-1.amazonaws.com/cfn-resource-specifications-us-gov-west-1-prod/latest/CloudFormationResourceSpecification.json"
  "us-gov-east-1|https://s3.us-gov-east-1.amazonaws.com/cfn-resource-specifications-us-gov-east-1-prod/latest/CloudFormationResourceSpecification.json"
  "us-east-1|https://d1uauaxba7bl26.cloudfront.net/latest/gzip/CloudFormationResourceSpecification.json"
)

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

: >"$dest/manifest.tsv.part"
for entry in "${sources[@]}"; do
  region="${entry%%|*}"
  url="${entry#*|}"
  out="$dest/spec-$region.json"
  status="$(curl --fail --silent --show-error --location --proto '=https' --max-time 300 --compressed \
    --write-out '%{http_code}' --output "$out.part" "$url")"
  # The gzip address may hand back gzip bytes without a Content-Encoding header; unpack them if so.
  if [[ "$(head -c 2 "$out.part" | od -An -tx1 | tr -d ' \n')" == "1f8b" ]]; then
    gzip -dc <"$out.part" >"$out"
    rm -f "$out.part"
  else
    mv "$out.part" "$out"
  fi
  version="$(grep -o '"ResourceSpecificationVersion"[^,}]*' "$out" | head -n 1 | sed 's/.*: *"\{0,1\}//; s/"\{0,1\} *$//')"
  size="$(wc -c <"$out" | tr -d ' ')"
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "spec-$region.json" "$url" "$status" "$(sha256_of "$out")" "$size" "$version" >>"$dest/manifest.tsv.part"
done
mv "$dest/manifest.tsv.part" "$dest/manifest.tsv"
cat "$dest/manifest.tsv"
