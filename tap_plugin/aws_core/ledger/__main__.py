"""Command line for the coverage ledger: ``fetch`` the schema bundle, ``build`` the ledger, ``check`` it.

    python -m tap_plugin.aws_core.ledger fetch --dest DIR
    python -m tap_plugin.aws_core.ledger build --cfn DIR_OR_ZIP [--out FILE]
    python -m tap_plugin.aws_core.ledger check --cfn DIR_OR_ZIP

``build`` and ``check`` are offline. Only ``fetch`` touches the network, with the standard library, over
https, to one fixed address, and refuses a body over a fixed size.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tomllib
import urllib.request
from pathlib import Path
from typing import Any

import jsonschema

from . import sources
from .build import Inputs, LedgerError, build_ledger, render

PACKAGE = Path(__file__).resolve().parent
PLUGIN = PACKAGE.parent
LEDGER_PATH = PACKAGE / "aws_coverage_ledger.json"
DECISIONS_PATH = PACKAGE / "decisions.json"
MANIFEST_PATH = PLUGIN / "collectors" / "boto3_collector" / "aws_resource_manifest.json"
PLUGIN_TOML = PLUGIN / "tap-plugin.toml"


def _load_validated(path: Path, schema_path: Path) -> Any:
    schema = json.loads(schema_path.read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    document = json.loads(path.read_text())
    jsonschema.Draft202012Validator(schema).validate(document)
    return document


def load_decisions() -> dict[str, Any]:
    decisions = _load_validated(DECISIONS_PATH, PACKAGE / "decisions.schema.json")
    assert isinstance(decisions, dict)
    return decisions


def gather_inputs(cfn_path: Path) -> Inputs:
    cfn, sha = sources.load_cfn_bundle(cfn_path)
    manifest = json.loads(MANIFEST_PATH.read_text())["entries"]
    models = frozenset(tomllib.loads(PLUGIN_TOML.read_text())["models"])
    with_endpoints, named = sources.partition_services()
    return Inputs(
        cfn=cfn,
        cfn_sha256=sha,
        botocore_version=sources.botocore_version(),
        boto=sources.botocore_services(),
        partitions=with_endpoints,
        named_prefixes=named,
        decisions=load_decisions(),
        models=models,
        manifest={entry["entity_type"]: entry for entry in manifest},
    )


def build_text(cfn_path: Path) -> str:
    ledger = build_ledger(gather_inputs(cfn_path))
    jsonschema.Draft202012Validator(json.loads((PACKAGE / "aws_coverage_ledger.schema.json").read_text())).validate(ledger)
    return render(ledger)


def fetch(dest: Path) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / "CloudformationSchema.zip"
    request = urllib.request.Request(sources.BUNDLE_URL, headers={"User-Agent": "aws-core-tap-ledger"})
    digest = hashlib.sha256()
    size = 0
    with urllib.request.urlopen(request, timeout=60) as response, target.open("wb") as out:  # noqa: S310 - fixed https URL
        while chunk := response.read(1 << 20):
            size += len(chunk)
            if size > sources.MAX_BUNDLE_BYTES:
                target.unlink()
                print(f"refused: body over {sources.MAX_BUNDLE_BYTES} bytes", file=sys.stderr)
                return 2
            digest.update(chunk)
            out.write(chunk)
    print(f"{target} {size} bytes sha256 {digest.hexdigest()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tap_plugin.aws_core.ledger", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("fetch", help="download the CloudFormation schema bundle")
    f.add_argument("--dest", type=Path, required=True)
    b = sub.add_parser("build", help="build the ledger from a bundle zip or extracted directory")
    b.add_argument("--cfn", type=Path, required=True)
    b.add_argument("--out", type=Path, default=LEDGER_PATH)
    c = sub.add_parser("check", help="exit 1 if the committed ledger differs from what the bundle builds")
    c.add_argument("--cfn", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "fetch":
        return fetch(args.dest)
    try:
        text = build_text(args.cfn)
    except (LedgerError, sources.SourceError) as exc:
        print(f"ledger refused:\n{exc}", file=sys.stderr)
        return 2
    summary = json.loads(text)["summary"]
    if args.command == "build":
        args.out.write_text(text)
        print(f"wrote {args.out}")
        print(json.dumps(summary, indent=1))
        return 0
    if LEDGER_PATH.read_text() == text:
        print("ledger is current")
        return 0
    print("ledger differs from the committed file; run `build` and review the diff", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
