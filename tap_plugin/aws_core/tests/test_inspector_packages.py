"""Inspector's vulnerable packages on the image host, keyed as computing_core's SBOM parser keys them (aws-core-tap#261,
req-aws-landing-zone-inspector-packages). fedramp_20x_vdr's reach walks finding <- CARRIES <- package <-
INSTALLS_PACKAGE <- host <- RUNS_IMAGE <- container; the last edge is the ECS reader's, the rest are written here.
"""

from __future__ import annotations

from typing import Any

import pytest
from tap_plugin.aws_core.collectors.boto3_collector.compliance import CARRIES, finding_ref, project
from tap_plugin.aws_core.collectors.boto3_collector.identity import composite_natural_key, node_ref
from tap_plugin.aws_core.collectors.boto3_collector.inspector import (
    IMAGE_HOST,
    INSPECTOR_FINDING,
    INSTALLS_PACKAGE,
    PACKAGE,
    os_ecosystem,
    package_identities,
)

from .test_inspector_findings import (
    DIGEST,
    REGION,
    _nodes,
    _reader,
    _Stubbed,
    ec2_instance,
    ecr_image,
    expect_list,
    expect_status,
    expect_totals,
    finding_arn,
    package_finding,
)


def pkg(name: str, version: str, manager: str, **extra: Any) -> dict[str, Any]:
    return {"name": name, "version": version, "packageManager": manager, **extra}


@pytest.mark.spec("req-aws-landing-zone-inspector-packages-1", "req-aws-landing-zone-inspector-packages-2")
@pytest.mark.parametrize(
    ("package", "platform", "key", "unmatched"),
    [
        (pkg("openssl", "3.0.8", "OS", release="1.amzn2023", epoch=1), "AMAZON_LINUX_2023", ("rpm", "openssl", "1:3.0.8-1.amzn2023"), None),
        (pkg("libc6", "2.36", "OS", release="9+deb12u3", epoch=0), "DEBIAN_12", ("deb", "libc6", "2.36-9+deb12u3"), None),
        (pkg("musl", "1.2.4", "OS", release="r1"), "ALPINE_3_18", ("apk", "musl", "1.2.4-r1"), None),
        (pkg("lodash", "4.17.20", "NPM"), None, ("npm", "lodash", "4.17.20"), None),
        (pkg("requests", "2.25.0", "POETRY"), None, ("pypi", "requests", "2.25.0"), None),
        (pkg("golang.org/x/net", "v0.7.0", "GOMOD"), None, ("golang", "golang.org/x/net", "v0.7.0"), None),
        (pkg("org.apache.logging.log4j:log4j-core", "2.14.1", "JAR"), None, None, "artifact id"),
        (pkg("openssl", "3.0.8", "OS"), "WINDOWS_SERVER_2022", None, "no known distribution family"),
        (pkg("thing", "1", "SOMETHING_NEW"), None, None, "no mapped type"),
    ],
)
def test_a_package_is_keyed_as_the_sbom_parser_keys_it(package: dict[str, Any], platform: Any, key: Any, unmatched: Any) -> None:
    [identity] = package_identities([package], platform)
    if key is None:
        assert identity["key"] is None and unmatched in identity["unmatched"]
    else:
        assert identity["key"] == dict(zip(("ecosystem", "name", "version"), key, strict=True))
        assert identity["unmatched"] is None


def test_os_families() -> None:
    assert os_ecosystem("UBUNTU_22_04") == "deb" and os_ecosystem("RHEL_9") == "rpm" and os_ecosystem(None) is None


@pytest.mark.spec("req-aws-landing-zone-inspector-packages-1")
def test_the_image_host_installs_each_keyed_package_sent_with_its_key_only() -> None:
    with _Stubbed() as aws:
        expect_status(aws.stub)
        expect_totals(aws.stub, "PACKAGE_VULNERABILITY", {"all": 2})
        expect_list(aws.stub, "PACKAGE_VULNERABILITY", "ACTIVE", [package_finding(1, ecr_image()), package_finding(2, ec2_instance())])
        expect_list(aws.stub, "PACKAGE_VULNERABILITY", "CLOSED", [])
        reader = _reader(aws)
        reader.inspector.read(REGION)
        aws.stub.assert_no_pending_responses()
    rows = {n["finding_arn"]: n for n in _nodes(reader, INSPECTOR_FINDING)}
    [identity] = rows[finding_arn(1)]["package_identities"]
    key = {"ecosystem": "rpm", "name": "openssl", "version": "1:3.0.2-1.amzn2023"}
    assert identity["key"] == key
    assert rows[finding_arn(2)]["package_identities"] is None, "an EC2 finding gets no package chain"
    assert "AMAZON_LINUX" not in repr(rows), "the platform is read in memory, never stored"
    [package] = [n for n in reader.result.nodes if n["entity"]["entity_type"] == PACKAGE]
    assert package["node"] == key and "name" not in package["entity"]
    host = node_ref(IMAGE_HOST, composite_natural_key({"realm": "oci-digest", "stable_id": DIGEST}))
    [edge] = [e["edge"] for e in reader.result.edges if e["edge"]["edge_type"] == INSTALLS_PACKAGE]
    assert (edge["from_ref"], edge["to_ref"]) == (host, node_ref(PACKAGE, composite_natural_key(key)))


@pytest.mark.spec("req-aws-landing-zone-inspector-packages-3")
def test_packages_carry_an_image_finding_instead_of_its_repository() -> None:
    key = {"ecosystem": "rpm", "name": "openssl", "version": "1:3.0.2-1.amzn2023"}
    base = {
        "finding_arn": finding_arn(1),
        "status": "ACTIVE",
        "title": "CVE-2026-0001 - openssl",
        "vulnerability_id": "CVE-2026-0001",
        "resource_type": "AWS_ECR_CONTAINER_IMAGE",
        "resource_id": ecr_image()["id"],
    }
    keyed = project([{**base, "package_identities": [{"name": "openssl", "key": key, "unmatched": None}]}], [])
    [carrier] = [e["edge"] for e in keyed.edges if e["edge"]["edge_type"] == CARRIES]
    assert (carrier["from_ref"], carrier["to_ref"]) == (node_ref(PACKAGE, composite_natural_key(key)), finding_ref(finding_arn(1)))
    unkeyed = project([{**base, "package_identities": [{"name": "x", "key": None, "unmatched": "why"}]}], [])
    [carrier] = [e["edge"] for e in unkeyed.edges if e["edge"]["edge_type"] == CARRIES]
    assert carrier["from_ref"].startswith("aws_core__aws_ecr_repository:"), "no keyed package: the repository carries it"


@pytest.mark.django_db
@pytest.mark.spec("req-aws-landing-zone-inspector-packages-3")
def test_reach_walks_from_the_neutral_finding_to_the_container_running_the_image() -> None:
    """The same walk fedramp_20x_vdr's reach Search makes (searches/reach.py, read 2026-11-20), over real grid rows."""
    from tap_grid.models import Edge
    from tap_grid.services import create_edge, create_node, get_node

    from .test_inspector_compliance import ACCOUNT, _collector, _loaded

    if not _loaded():
        pytest.skip("compliance_core is not loaded on this stack")

    def node(entity_type: str, fields: dict[str, Any]) -> Any:
        result = create_node(entity_type, fields)
        assert result.success, result.errors
        return get_node(result.entity_id)

    key = {"ecosystem": "rpm", "name": "openssl", "version": "1:3.0.2-1.amzn2023"}
    host = node(IMAGE_HOST, {"realm": "oci-digest", "stable_id": DIGEST, "kind": "container"})
    package = node(PACKAGE, dict(key))
    container = node("aws_core__aws_ecs_container", {"name": "web", "container_arn": "arn:aws-us-gov:ecs:us-gov-west-1:111122223333:container/c/1"})
    create_edge(host.entity, package.entity, INSTALLS_PACKAGE)
    create_edge(container.entity, host.entity, "RUNS_IMAGE__computing_core")
    node(
        INSPECTOR_FINDING,
        {
            "name": "f",
            "finding_arn": finding_arn(1),
            "account_id": ACCOUNT,
            "status": "ACTIVE",
            "vulnerability_id": "CVE-2026-0001",
            "resource_type": "AWS_ECR_CONTAINER_IMAGE",
            "resource_id": ecr_image()["id"],
            "image_digest": DIGEST,
            "package_identities": [{"name": "openssl", "version": "3.0.2", "package_manager": "OS", "key": key, "unmatched": None}],
        },
    )
    assert _collector()._project_inspector_findings({"inspector_compliance_findings": True}, ACCOUNT) is None

    live = Edge.objects.filter(entity__deleted_at__isnull=True)
    [(carrier, finding)] = live.filter(edge_type=CARRIES).values_list("from_entity_id", "to_entity_id")
    assert carrier == package.entity_id
    hosts = set(live.filter(edge_type=INSTALLS_PACKAGE, to_entity_id=carrier).values_list("from_entity_id", flat=True))
    containers = set(live.filter(edge_type="RUNS_IMAGE__computing_core", to_entity_id__in=hosts).values_list("from_entity_id", flat=True))
    assert containers == {container.entity_id}
    assert live.filter(edge_type="CONCERNS_COMPLIANCE_VULNERABILITY__compliance_core", from_entity_id=finding).exists()
