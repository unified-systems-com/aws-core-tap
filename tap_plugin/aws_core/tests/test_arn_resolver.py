"""An ARN resolves to the aws_core node keyed by it, whatever its type (aws-core-tap#242).

``arn_resolver`` reads each model's ``ARN_RESOURCE`` and ``NATURAL_KEY`` from the entity registry and the vendored
``arn_formats.json``; it keeps no table of types. These tests drive it over the real models and formats, and over a
small synthetic set where the rule itself is under test. Security Hub's use of it (``findings._asff_target``) is
covered here case by case and end to end in ``test_security_findings.py``. No AWS call is made.
"""

from __future__ import annotations

import json
import re

import pytest

from tap_plugin.aws_core.collectors.boto3_collector import arn_resolver, iam_policy
from tap_plugin.aws_core.collectors.boto3_collector.arn_resolver import (
    ArnResolver,
    arn_keyed_types,
    default_resolver,
    resolve_arn,
)
from tap_plugin.aws_core.collectors.boto3_collector.findings import (
    CONCERNS_RESOURCE,
    SECURITYHUB_FINDING,
    _asff_target,
)

P = "aws"
R = "us-east-1"
A = "123456789012"

RDS_CLUSTER_ARN = f"arn:{P}:rds:{R}:{A}:cluster:orders-aurora"
KMS_KEY_ARN = f"arn:{P}:kms:{R}:{A}:key/1234abcd-12ab-34cd-56ef-1234567890ab"
INSTANCE_ARN = f"arn:{P}:ec2:{R}:{A}:instance/i-0abc1234def567890"
BUCKET_ARN = f"arn:{P}:s3:::audit-logs-bucket"
USER_ARN = f"arn:{P}:iam::{A}:user/ops/ci-deployer"
ROLE_ARN = f"arn:{P}:iam::{A}:role/CrossAccountAudit"

FORMATS: dict[str, list[str]] = json.loads(arn_resolver.ARN_FORMATS.read_text())["resources"]
_PLACEHOLDER = re.compile(r"\$\{(\w+)\}|\*")


def _sample(fmt: str) -> str:
    """A concrete ARN for a reference format: partition, region and account filled by position, every other
    placeholder with a distinct token."""
    count = iter(range(1, 100))
    head = fmt.split(":", 5)
    head[1], head[3], head[4] = P, (R if head[3] else ""), (A if head[4].startswith("${") else head[4])
    return _PLACEHOLDER.sub(lambda _m: f"v{next(count)}x", ":".join(head))


def _shape(fmt: str) -> str:
    return _PLACEHOLDER.sub("{}", fmt)


class TestSecurityHubTarget:
    """``_asff_target``: what a Security Hub ``Resources[]`` entry points at."""

    @pytest.mark.spec("req-aws-landing-zone-findings-2")
    @pytest.mark.parametrize(
        ("resource_type", "resource_id", "expected"),
        [
            ("AwsEc2Instance", INSTANCE_ARN, ("aws_core__aws_ec2_instance", "i-0abc1234def567890")),
            ("AwsS3Bucket", BUCKET_ARN, ("aws_core__aws_s3_bucket", BUCKET_ARN)),
            ("AwsIamUser", USER_ARN, ("aws_core__aws_iam_user", USER_ARN)),
            ("AwsIamRole", ROLE_ARN, ("aws_core__aws_iam_role", ROLE_ARN)),
        ],
    )
    def test_the_four_original_types_still_resolve(self, resource_type: str, resource_id: str, expected: tuple) -> None:
        assert _asff_target(resource_type, resource_id) == expected

    @pytest.mark.spec("req-aws-landing-zone-findings-2")
    @pytest.mark.parametrize(
        ("resource_type", "resource_id", "expected"),
        [
            ("AwsRdsDbCluster", RDS_CLUSTER_ARN, ("aws_core__aws_rds_db_cluster", RDS_CLUSTER_ARN)),
            ("AwsKmsKey", KMS_KEY_ARN, ("aws_core__aws_kms_key", KMS_KEY_ARN)),
            # The ASFF type plays no part: the ARN alone says what it names.
            ("Other", KMS_KEY_ARN, ("aws_core__aws_kms_key", KMS_KEY_ARN)),
        ],
    )
    def test_any_arn_keyed_type_resolves_by_its_arn(self, resource_type: str, resource_id: str, expected: tuple) -> None:
        assert _asff_target(resource_type, resource_id) == expected

    @pytest.mark.spec("req-aws-landing-zone-findings-2")
    @pytest.mark.parametrize(
        ("resource_type", "resource_id"),
        [
            # A service aws_core does not model.
            ("Other", f"arn:{P}:madeupservice:{R}:{A}:widget/w-1"),
            # A modelled service, a resource shape no vendored format has.
            ("Other", f"arn:{P}:kms:{R}:{A}:custom-key-store/cks-1"),
            # Not an ARN at all: an address (stored redacted), or a bare id.
            ("Other", "2001:db8::7"),
            ("AwsEc2Instance", "i-0abc1234def567890"),
            # An EC2 instance entry whose ARN is not an instance's.
            ("AwsEc2Instance", f"arn:{P}:ec2:{R}:{A}:volume/vol-1"),
            # An EC2 instance is keyed by its id, so its ARN never resolves without the ASFF type saying so.
            ("Other", INSTANCE_ARN),
        ],
    )
    def test_an_unresolvable_id_names_nothing(self, resource_type: str, resource_id: str) -> None:
        assert _asff_target(resource_type, resource_id) is None


#: Formats for the rule's own tests: an API and its stages, two resources of one shape, a shared resource type, a
#: policy wildcard, and a type keyed by an id.
SYNTHETIC_FORMATS: dict[str, list[str]] = {
    "x:api": ["arn:${Partition}:x:${Region}::/apis/${ApiId}"],
    "x:stage": ["arn:${Partition}:x:${Region}::/apis/${ApiId}/stages/${StageName}"],
    "x:alias": ["arn:${Partition}:x:${Region}:${Account}:fn:${Name}:${Alias}"],
    "x:version": ["arn:${Partition}:x:${Region}:${Account}:fn:${Name}:${Version}"],
    "x:alarm": ["arn:${Partition}:x:${Region}:${Account}:alarm:${Name}"],
    "x:thing": ["arn:${Partition}:x:${Region}:${Account}:thing:*"],
    "x:byid": ["arn:${Partition}:x:${Region}:${Account}:byid/${Id}"],
}


class TestTheRule:
    """The resolver's rule, over a synthetic set of formats and models."""

    @staticmethod
    def _model(entity_type: str, resource: str | None, key: tuple[str, ...]) -> type:
        return type("M", (), {"ENTITY_TYPE": entity_type, "ARN_RESOURCE": resource, "NATURAL_KEY": key})

    def _resolver(self) -> ArnResolver:
        models = [
            self._model("api", "x:api", ("api_arn",)),
            self._model("alias", "x:alias", ("arn",)),
            self._model("version", "x:version", ("arn",)),
            self._model("alarm", "x:alarm", ("alarm_arn",)),
            self._model("composite_alarm", "x:alarm", ("alarm_arn",)),
            self._model("thing", "x:thing", ("thing_arn",)),
            self._model("byid", "x:byid", ("byid_id",)),
            self._model("composite", "x:stage", ("api_arn", "stage_name")),
            self._model("none", None, ("arn",)),
        ]
        return ArnResolver(SYNTHETIC_FORMATS, arn_keyed_types(models))

    def test_only_a_single_arn_field_key_counts_as_keyed_by_the_arn(self) -> None:
        keyed = arn_keyed_types(
            [
                self._model("a", "x:api", ("arn",)),
                self._model("b", "x:byid", ("byid_id",)),
                self._model("c", "x:stage", ("api_arn", "stage_name")),
                self._model("d", None, ("arn",)),
            ]
        )
        assert keyed == {"x:api": ["a"]}

    def test_the_most_specific_format_wins_even_when_its_type_cannot_be_keyed(self) -> None:
        resolver = self._resolver()
        api = f"arn:{P}:x:{R}::/apis/a1"
        stage = f"arn:{P}:x:{R}::/apis/a1/stages/prod"
        assert resolver.resolve(api) == ("api", api)
        # The looser api format also matches (a placeholder may hold a slash), but the stage format is more
        # specific; the stage type has a composite key, so the ARN names nothing rather than a wrong api.
        assert resolver.resource_of(stage) == "x:stage"
        assert resolver.resolve(stage) is None

    def test_two_equally_specific_formats_name_nothing(self) -> None:
        assert self._resolver().resolve(f"arn:{P}:x:{R}:{A}:fn:f1:live") is None

    def test_a_resource_type_several_models_share_names_nothing(self) -> None:
        assert self._resolver().resolve(f"arn:{P}:x:{R}:{A}:alarm:a1") is None

    def test_a_policy_wildcard_stands_for_one_resource_id(self) -> None:
        arn = f"arn:{P}:x:{R}:{A}:thing:T1"
        assert self._resolver().resolve(arn) == ("thing", arn)

    def test_a_type_keyed_by_something_else_names_nothing(self) -> None:
        assert self._resolver().resolve(f"arn:{P}:x:{R}:{A}:byid/b-1") is None

    def test_region_and_account_may_be_empty_and_partition_is_any(self) -> None:
        arn = f"arn:aws-us-gov:x:{R}::/apis/a1"
        assert self._resolver().resolve(arn) == ("api", arn)
        assert self._resolver().resolve(f"arn:{P}:x::{A}:thing:T1") == ("thing", f"arn:{P}:x::{A}:thing:T1")


class TestOverTheRealModels:
    """The resolver built from the registry and ``arn_formats.json``."""

    def test_it_reads_the_same_vendored_file_as_the_refresh(self) -> None:
        assert arn_resolver.ARN_FORMATS == iam_policy.ARN_FORMATS

    @pytest.mark.spec("req-aws-landing-zone-findings-2")
    def test_every_arn_keyed_type_resolves_its_own_arn_unless_aws_gives_two_types_one_shape(self) -> None:
        """For each type keyed by its ARN whose resource type no other model shares, an ARN built from each of its
        formats resolves to that type. The one exception is a format AWS gives two resource types in the same shape
        (a Lambda alias and a version): that ARN names nothing, and the test checks the shapes really are the same."""
        from tap_grid.registry import get_model_class, list_entity_types

        resolver = default_resolver()
        models = [get_model_class(t) for t in list_entity_types() if t.startswith("aws_core__")]
        keyed = {r: types for r, types in arn_keyed_types(models).items() if len(types) == 1}
        assert len(keyed) > 600, "most aws_core types are keyed by their ARN"
        resolved = 0
        for resource, (entity_type,) in keyed.items():
            for fmt in FORMATS[resource]:
                arn = _sample(fmt)
                if resolver.resource_of(arn) is None:
                    rivals = [
                        other
                        for other, formats in FORMATS.items()
                        if other != resource and any(_shape(f) == _shape(fmt) for f in formats)
                    ]
                    assert rivals, f"{arn} ({resource}) names nothing, and no other resource type has its shape"
                    continue
                assert resolve_arn(arn) == (entity_type, arn), resource
                resolved += 1
        assert resolved > 600

    @pytest.mark.spec("req-aws-landing-zone-findings-2")
    def test_concerns_resource_may_point_at_any_type_it_resolves(self) -> None:
        from tap_grid.constraints import validate_edge

        for target in ("aws_core__aws_rds_db_cluster", "aws_core__aws_kms_key", "aws_core__aws_ec2_instance"):
            validate_edge(SECURITYHUB_FINDING, target, CONCERNS_RESOURCE)

    @pytest.mark.spec("req-aws-landing-zone-findings-2")
    def test_guardduty_and_access_analyzer_keep_their_named_targets(self) -> None:
        """The open target is Security Hub's alone: the other finding types still refuse a type they
        do not name, because their models declare the edge with their targets (PR 245 review)."""
        from tap_grid.constraints import InvalidEdgeError, validate_edge

        allowed = {
            "aws_core__aws_guardduty_finding": (
                "aws_core__aws_ec2_instance",
                "aws_core__aws_s3_bucket",
                "aws_core__aws_iam_user",
            ),
            "aws_core__aws_access_analyzer_finding": (
                "aws_core__aws_s3_bucket",
                "aws_core__aws_iam_role",
                "aws_core__aws_iam_user",
            ),
        }
        for source, targets in allowed.items():
            for target in targets:
                validate_edge(source, target, CONCERNS_RESOURCE)
            for target in ("aws_core__aws_kms_key", "aws_core__aws_rds_db_cluster"):
                with pytest.raises(InvalidEdgeError):
                    validate_edge(source, target, CONCERNS_RESOURCE)
