"""Live trial of collection selection (``req-aws-collector-selection-5``, ``-14``), read-only against a real account.

Run inside the stack's web container, which holds the collector's secret:

    scripts/dc exec -T web uv run python manage.py shell -c \
      "exec(open('/app/_dev-plugins/aws_core/tools/validate/selection_live.py').read())"

It runs the real ``Boto3Collector.run()`` three times and writes to this stack's grid only (never to AWS, and never
to the secrets store: the selection keys are added to an in-memory copy of the collector's secret):

1. ``include_types: ["ec2:vpc", "ec2:subnet"]``: both types land.
2. ``include_types: ["ec2:vpc"]``: the subnets of run 1 must be untouched (keep-absent), the run must state no
   completeness (no surface, no ``declare_no_surfaces``), and nothing may be tombstoned.
3. ``include_types: ["ec2:subnet"]``: the edge from a subnet to its VPC is not emitted and the run says so.

Every client is built from a session with ``readguard`` installed, so a write operation is refused before it is sent.
The result is printed between ``SELECTION_JSON_BEGIN`` and ``SELECTION_JSON_END``: counts, codes and booleans only,
never an account number, a resource id or a message.
"""

import json
import sys
import uuid

from tap_auth.actors import COLLECTOR, acting_as, get_builtin_actor
from tap_cares.collectors.config import CollectorConfig
from tap_cares.secrets.models import Secret
from tap_grid.registry import get_model_class

from tap_plugin.aws_core.collectors.boto3_collector import collector as collector_mod
from tap_plugin.aws_core.collectors.boto3_collector import credentials as cred
from tap_plugin.aws_core.collectors.boto3_collector.collector import Boto3Collector, Boto3CollectorError

# exec() from `manage.py shell -c` has no usable __file__; the repository is mounted at this path in the container.
sys.path.insert(0, "/app/_dev-plugins/aws_core/tools/validate")
import readguard  # noqa: E402

_VPC, _SUBNET = "aws_core__aws_vpc", "aws_core__aws_subnet"
_real_resolve = cred.resolve_secret
_real_build_session = collector_mod.build_session


def _live_ids(entity_type):
    model = get_model_class(entity_type)
    return set(model.objects.filter(entity__deleted_at__isnull=True).values_list("entity_id", flat=True))


def _fingerprint(entity_type):
    model = get_model_class(entity_type)
    rows = model.objects.filter(entity__deleted_at__isnull=True).order_by("entity_id")
    return [(str(r.entity_id), r.entity.updated_at.isoformat() if hasattr(r.entity, "updated_at") else None) for r in rows]


def _select(include):
    def resolve(ref):
        secret = _real_resolve(ref)
        return Secret(
            ref=secret.ref,
            kind=secret.kind,
            description=secret.description,
            data={**secret.data, "include_types": include},
            metadata=secret.metadata,
            source_path=secret.source_path,
        )

    cred.resolve_secret = resolve

    def guarded(data):
        session = _real_build_session(data)
        readguard.install(session)
        return session

    collector_mod.build_session = guarded


def _run(include):
    _select(include)
    collector = Boto3Collector(CollectorConfig(collector_entity_id=uuid.uuid7(), collection_job_entity_id=uuid.uuid7()))
    failed = None
    try:
        # What the collector task does (tap_cares/tasks.py): run as the built-in collector actor.
        with acting_as(get_builtin_actor(COLLECTOR), batch_name="aws_core selection live trial"):
            collector.run()
    except Boto3CollectorError as exc:
        failed = type(exc).__name__
    info = [r["message_code"] for r in collector.results["info"]]
    return {
        "include_types": include,
        "failed": failed,
        "errors": [e["message_code"] for e in collector.results["error"]],
        "surfaces": len(collector._surfaces),
        "declared_no_surfaces": bool(collector._surfaces_declared and not collector._surfaces),
        "states_completeness": bool(collector._surfaces_declared),
        "edges_not_selected": next(
            (r["message_data"]["edges"] for r in collector.results["info"] if r["message_code"] == "EDGES_NOT_SELECTED"), 0
        ),
        "edge_dropped_warnings": sum(1 for w in collector.results["warn"] if w["message_code"] == "EDGE_DROPPED"),
        "selection_applied": "SELECTION_APPLIED" in info,
    }


def main():
    out = {"runs": []}
    try:
        first = _run(["ec2:vpc", "ec2:subnet"])
        first["vpcs_live"], first["subnets_live"] = len(_live_ids(_VPC)), len(_live_ids(_SUBNET))
        subnets_before, fingerprint_before = _live_ids(_SUBNET), _fingerprint(_SUBNET)
        out["runs"].append(first)

        second = _run(["ec2:vpc"])
        second["subnets_live"] = len(_live_ids(_SUBNET))
        second["subnets_unchanged"] = _live_ids(_SUBNET) == subnets_before and _fingerprint(_SUBNET) == fingerprint_before
        out["runs"].append(second)

        third = _run(["ec2:subnet"])
        third["subnets_live"] = len(_live_ids(_SUBNET))
        out["runs"].append(third)
    finally:
        cred.resolve_secret = _real_resolve
        collector_mod.build_session = _real_build_session
    print("SELECTION_JSON_BEGIN")
    print(json.dumps(out, indent=1))
    print("SELECTION_JSON_END")


main()
