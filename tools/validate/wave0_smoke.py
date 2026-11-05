"""Wave 0 of live validation: a read-only call-path smoke over every manifest-driven type.

Run inside the stack's web container (it needs the collector's own secret, Django and boto3):

    scripts/dc exec -T -e WAVE0_LIMIT=5 web uv run python manage.py shell -c \\
        "exec(open('/app/_dev-plugins/aws_core/tools/validate/wave0_smoke.py').read())"

For each manifest entry it drives the real engine path (iter_source, project_item, resolve_node_tags) with the
collector identity, in the credential's regions, and records one result per (type, region): outcome, rows, calls,
seconds, error class. It builds no batch, submits nothing to the grid, and writes nothing to AWS. A before-call guard
refuses any operation whose name is not a read verb. The output holds counts and error codes only, never resource
content. Specification: specs/spec-aws-core-live-validation.md (req-aws-core-livevalidation-smoke).

Environment: WAVE0_LIMIT (first N entries), WAVE0_ONLY (comma-separated fnmatch patterns on entity type), WAVE0_OUT
(json path in the container).
"""

import fnmatch
import json
import os
import re
import time

from botocore.exceptions import BotoCoreError, ClientError, EndpointConnectionError

from tap_plugin.aws_core.collectors.boto3_collector.collector import resolve_node_tags
from tap_plugin.aws_core.collectors.boto3_collector.credentials import (
    AWS_SECRET_REF,
    account_mismatch_error,
    build_session,
    caller_account_id,
    client_factory,
    resolve_aws_secret,
    resolve_partition,
    resolve_regions,
)
from tap_plugin.aws_core.collectors.boto3_collector.customfns import build_custom_fn_registry
from tap_plugin.aws_core.collectors.boto3_collector.ledger import CallLedger
from tap_plugin.aws_core.collectors.boto3_collector.manifest import manifest_entries
from tap_plugin.aws_core.collectors.boto3_collector.outcomes import classify as collector_outcome
from tap_plugin.aws_core.collectors.boto3_collector.partition import entry_unavailable_reason
from tap_plugin.aws_core.collectors.boto3_collector.projection import ProjectionError, project_item
from tap_plugin.aws_core.collectors.boto3_collector.source import SourceError, iter_source

import sys

# exec() from `manage.py shell -c` has no usable __file__; the repository is mounted at this path in the container.
sys.path.insert(0, "/app/_dev-plugins/aws_core/tools/validate")
from readguard import NonReadCall, install  # noqa: E402


def _scrub(text):
    """Account numbers do not belong in a committed record: replace any 12-digit run."""
    return re.sub(r"\b\d{12}\b", "<account>", str(text))


def _classify(exc, entry=None, partition=None):
    if isinstance(exc, NonReadCall):
        return "blocked-non-read-call", str(exc)
    if entry is not None and partition is not None:
        # The collector's own named outcomes come first, so the smoke reports what a real run would record
        # (not configured in this account, not offered in this partition, throttled) and not a second opinion.
        named = collector_outcome(entry, exc, partition)
        if named is not None:
            return named.kind.replace("_", "-"), named.code
    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "ClientError")
        if code in (
            "AccessDenied", "AccessDeniedException", "UnauthorizedOperation", "AuthorizationError", "UnauthorizedAccess",
            # The service's own spelling of a refused caller (IoT, API Gateway, License Manager, Translate, Resource Groups).
            "UnauthorizedException", "AuthorizationException", "NotAuthorizedException", "ForbiddenException",
        ):
            return "access-denied", code
        if code in ("ThrottlingException", "Throttling", "RequestLimitExceeded", "TooManyRequestsException"):
            return "throttled", code
        if code in ("InvalidAction", "UnknownOperationException", "UnsupportedOperation", "OptInRequired", "SubscriptionRequiredException"):
            return "unsupported", code
        if code in ("ValidationException", "InvalidParameterValue", "InvalidParameterCombination", "MissingParameter", "InvalidInput", "BadRequestException"):
            return "validation", code
        return "error", code
    if isinstance(exc, EndpointConnectionError):
        return "unsupported-in-partition", "EndpointConnectionError"
    if isinstance(exc, (SourceError, ProjectionError)):
        return "collector-error", type(exc).__name__
    if isinstance(exc, BotoCoreError):
        return "error", type(exc).__name__
    return "error", type(exc).__name__


def main():
    secret = resolve_aws_secret(AWS_SECRET_REF)
    data = dict(secret.data)
    regions = resolve_regions(data)
    partition = resolve_partition(data, regions)
    ledger = CallLedger()
    session = build_session(data)
    ledger.attach(session)
    install(session)  # readguard's before-parameter-build handler, registered before any client is built
    account = caller_account_id(session, regions[0], timeout_seconds=30)
    mismatch = account_mismatch_error(data, account)
    if mismatch:
        raise SystemExit(f"STOP: {mismatch}")
    print(f"WAVE0 identity ok: partition {partition}, regions {regions}, account matches the declared guard", flush=True)

    entries = sorted(manifest_entries(), key=lambda e: e["entity_type"])
    only = os.environ.get("WAVE0_ONLY")
    if only:
        pats = [x for x in only.split(",") if x]
        entries = [e for e in entries if any(fnmatch.fnmatchcase(e["entity_type"], x) for x in pats)]
    limit = int(os.environ.get("WAVE0_LIMIT", "0") or 0)
    if limit:
        entries = entries[:limit]
    custom_fns = build_custom_fn_registry()
    results = []
    start = time.time()
    for n, entry in enumerate(entries, 1):
        etype = entry["entity_type"]
        not_offered = entry_unavailable_reason(partition, entry)
        if not_offered and not os.environ.get("WAVE0_IGNORE_AVAILABILITY"):
            results.append({"entity_type": etype, "region": None, "outcome": "unsupported-in-partition", "error_class": "ledger-says-not-offered", "rows": 0, "calls": 0, "seconds": 0.0})
            continue
        for region in regions if entry["scope"] == "regional" else regions[:1]:
            before = len(ledger.entries)
            t0 = time.time()
            rec = {"entity_type": etype, "region": region if entry["scope"] == "regional" else "global", "rows": 0, "projection_errors": 0, "tag_errors": 0}
            try:
                items = list(
                    iter_source(
                        entry,
                        client_for=client_factory(session, region),
                        custom_fns=custom_fns,
                        fn_context=session,
                        walk=None,
                        truncated=None,
                        account_id=account,
                        scope={"partition": partition, "region": region, "account": account},
                    )
                )
                rec["rows"] = len(items)
                rec["outcome"] = "ok" if items else "empty"
                for item in items[:50]:  # a sample is enough to prove the mapping; volume is counted above
                    try:
                        project_item(entry, item)
                    except Exception as exc:  # noqa: BLE001 - the smoke records every projection failure by class
                        rec["projection_errors"] += 1
                        rec.setdefault("projection_error_class", type(exc).__name__)
                    try:
                        resolve_node_tags(entry, item, rgta_map={}, client_for=client_factory(session, region), rgta_unread=True)
                    except Exception as exc:  # noqa: BLE001
                        rec["tag_errors"] += 1
                        rec.setdefault("tag_error_class", _classify(exc)[1])
            except Exception as exc:  # noqa: BLE001 - every failure is a result, none stops the wave
                rec["outcome"], rec["error_class"] = _classify(exc, entry, partition)
                if os.environ.get("WAVE0_MESSAGES"):  # local debugging only: messages can name resources, so they are never recorded by default
                    rec["error_message"] = _scrub(str(exc)[:200])
            new = ledger.entries[before:]
            if rec.get("outcome") == "collector-error" and any(c["outcome"] == "denied" for c in new):
                # The engine wraps a refused call in a SourceError that drops the error code; the ledger kept it.
                rec["outcome"], rec["error_class"] = "access-denied", "AccessDenied"
            rec["calls"] = len(new)
            rec["failed_calls"] = sorted({f"{c['service']}.{c['operation']}:{c['outcome']}" for c in new if c["outcome"] not in ("ok", "absent")})
            rec["calls_made"] = sorted({f"{c['service']}.{c['operation']}" for c in new})
            rec["call_outcomes"] = {o: sum(1 for c in new if c["outcome"] == o) for o in sorted({c["outcome"] for c in new})}
            if rec.get("outcome") == "empty" and not new:
                # No AWS call was made (a parent-dependent type with no parent resources): the type's own call
                # path was never reached, so this is not evidence that it works.
                rec["outcome"] = "not-exercised"
            rec["seconds"] = round(time.time() - t0, 2)
            results.append(rec)
        if n % 50 == 0:
            print(f"WAVE0 progress {n}/{len(entries)} entries, {round(time.time() - start)}s", flush=True)
    out = {"partition": partition, "regions": regions, "entries": len(entries), "results": results}
    path = os.environ.get("WAVE0_OUT")
    if path:
        with open(path, "w") as fh:
            json.dump(out, fh, indent=1, sort_keys=True)
    print("WAVE0_JSON_BEGIN")
    print(json.dumps(out, sort_keys=True))
    print("WAVE0_JSON_END")


main()
