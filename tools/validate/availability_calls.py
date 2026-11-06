"""One real read-only call per service in each GovCloud region and FIPS setting, to settle the DNS matrix.

Run inside the stack's web container (it needs the collector's own secret):

    scripts/dc exec -T web uv run python manage.py shell -c \\
      "RUN_AVAILABILITY_CALLS = True; exec(open('/app/_dev-plugins/aws_core/tools/validate/availability_calls.py').read())"

``availability_matrix.py`` looked hosts up in DNS; that says a host has no record, not that a signed call to it fails.
For every service the manifest marks, or the matrix found to differ between variants, this makes one read call (the
first manifest entry that one call can read, with its own parameters) per region and FIPS setting through the collector's
own client configuration and the read guard, and records only whether the service answered: ``no_endpoint`` (the
connection could not be made) or ``answered`` (the service replied, with data or with an error such as a refusal).
The result is printed between ``CALLS_JSON_BEGIN`` and ``CALLS_JSON_END``: service and operation names, regions and
outcome words only.
"""

import concurrent.futures
import json
import sys

from botocore import xform_name
from botocore.exceptions import BotoCoreError, ClientError, ConnectTimeoutError, EndpointConnectionError

from tap_plugin.aws_core.collectors.boto3_collector import collector as collector_mod
from tap_plugin.aws_core.collectors.boto3_collector import credentials as cred
from tap_plugin.aws_core.collectors.boto3_collector.credentials import client_config
from tap_plugin.aws_core.collectors.boto3_collector.manifest import manifest_entries

# exec() from `manage.py shell -c` has no usable __file__; the repository is mounted at this path in the container.
sys.path.insert(0, "/app/_dev-plugins/aws_core/tools/validate")
import readguard  # noqa: E402

REGIONS = ("us-gov-west-1", "us-gov-east-1")


def _probe_entries(services):
    chosen = {}
    for entry in manifest_entries():
        source = entry.get("source") or {}
        if entry["service"] in services and entry["service"] not in chosen and "aws_op" in source and "per" not in source and "bind" not in source:
            chosen[entry["service"]] = entry
    return chosen


def _call(session, entry, region, fips):
    source = entry["source"]
    client = session.client(entry["service"], region_name=region, config=client_config(use_fips_endpoint=fips))
    try:
        getattr(client, xform_name(source["aws_op"]))(**dict(source.get("params") or {}))
        return "answered"
    except (EndpointConnectionError, ConnectTimeoutError):
        return "no_endpoint"
    except (ClientError, BotoCoreError):
        return "answered"


def main(matrix_services):
    secret = cred.resolve_secret(collector_mod.AWS_SECRET_REF)
    session = collector_mod.build_session(secret.data)
    readguard.install(session)
    entries = _probe_entries(set(matrix_services))
    jobs = [(entry, region, fips) for entry in entries.values() for region in REGIONS for fips in (False, True)]
    with concurrent.futures.ThreadPoolExecutor(12) as pool:
        outcomes = list(pool.map(lambda j: _call(session, *j), jobs))
    results = [
        {
            "service": entry["service"],
            "entity_type": entry["entity_type"],
            "operation": entry["source"]["aws_op"],
            "region": region,
            "fips": fips,
            "outcome": outcome,
        }
        for (entry, region, fips), outcome in zip(jobs, outcomes, strict=True)
    ]
    print("CALLS_JSON_BEGIN")
    print(json.dumps(results, indent=1))
    print("CALLS_JSON_END")


if globals().get("RUN_AVAILABILITY_CALLS") is True:
    main(globals()["AVAILABILITY_SERVICES"])
