"""Which service hosts exist in each GovCloud region, with FIPS on and off (``req-aws-collector-partition-13``).

Run inside the stack's web container (it needs the plugin and botocore, and the network for DNS):

    scripts/dc exec -T web uv run python manage.py shell -c \\
      "RUN_AVAILABILITY_MATRIX = True; exec(open('/app/_dev-plugins/aws_core/tools/validate/availability_matrix.py').read())"

For every manifest entry one call can read (a single operation, no parent to fan out from), it works out the host the
call would be sent to in each region and FIPS setting (the request is built unsigned and stopped before it is sent) and
looks the host up in DNS. It makes no AWS call and reads no credential. A host that resolves says the service has an
endpoint there; it does not say the operation works. The result is printed between ``MATRIX_JSON_BEGIN`` and
``MATRIX_JSON_END``: service names, operation names and booleans only.
"""

import collections
import json

from tap_plugin.aws_core.collectors.boto3_collector.endpoint_probe import EndpointProbe, request_host
from tap_plugin.aws_core.collectors.boto3_collector.manifest import manifest_entries
from tap_plugin.aws_core.collectors.boto3_collector.partition import entry_unavailable_reason

PARTITION = "aws-us-gov"
REGIONS = ("us-gov-west-1", "us-gov-east-1")
VARIANTS = [(region, fips) for region in REGIONS for fips in (False, True)]


def _label(region, fips):
    return region.replace("us-gov-", "") + ("-fips" if fips else "")


def main():
    control = request_host("sts", REGIONS[0], "GetCallerIdentity")
    probe = EndpointProbe(control)
    if not probe.usable:
        print("MATRIX_JSON_BEGIN")
        print(json.dumps({"usable": False, "why": "the control host (STS) does not resolve from here"}))
        print("MATRIX_JSON_END")
        return
    services = collections.defaultdict(lambda: collections.defaultdict(dict))  # service -> host-key -> variant -> bool
    unprobeable = collections.Counter()
    listed = {}
    for entry in manifest_entries():
        source = entry.get("source") or {}
        service = entry["service"]
        listed_here = bool(entry_unavailable_reason(PARTITION, entry))
        if "aws_op" not in source or "per" in source or "bind" in source:
            unprobeable[service] += 1
            continue
        operation, params = str(source["aws_op"]), dict(source.get("params") or {})
        for region, fips in VARIANTS:
            host = request_host(service, region, operation, params, use_fips=fips)
            if host is None:
                continue
            found = probe.resolves(host)
            services[service][(operation, host.split(".")[0])][_label(region, fips)] = found
            listed[(service, operation)] = listed_here
    differing, absent_everywhere, listed_but_resolving, partial = [], [], [], []
    for service, ops in sorted(services.items()):
        per_variant = collections.defaultdict(list)
        for variants in ops.values():
            for label, found in variants.items():
                per_variant[label].append(found)
        summary = {label: ("all" if all(v) else "none" if not any(v) else "some") for label, v in per_variant.items()}
        entry_listed = any(listed.get((service, op)) for (op, _prefix) in ops)
        if len(set(summary.values())) > 1:
            differing.append({"service": service, "listed": entry_listed, "by_variant": summary})
        elif set(summary.values()) == {"none"}:
            absent_everywhere.append({"service": service, "listed": entry_listed})
        elif set(summary.values()) == {"some"}:
            partial.append({"service": service, "listed": entry_listed})
        if entry_listed and any(v != "none" for v in summary.values()):
            listed_but_resolving.append({"service": service, "by_variant": summary})
    out = {
        "usable": True,
        "variants": [_label(r, f) for r, f in VARIANTS],
        "services_checked": len(services),
        "hosts_checked": probe.hosts_checked,
        "entries_not_probeable_by_service": sum(unprobeable.values()),
        "differ_between_variants": differing,
        "no_host_in_any_variant": absent_everywhere,
        "some_operations_resolve_some_do_not": partial,
        "listed_not_offered_but_a_host_resolves": listed_but_resolving,
    }
    print("MATRIX_JSON_BEGIN")
    print(json.dumps(out, indent=1))
    print("MATRIX_JSON_END")


if globals().get("RUN_AVAILABILITY_MATRIX") is True:
    main()
