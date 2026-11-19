"""An ARN resolves to the aws_core node it names, whatever its type and however it is keyed (aws-core-tap#242, #252).

``arn_resolver`` reads each model's ``ARN_RESOURCE`` and ``NATURAL_KEY`` from the entity registry, each natively keyed
type's identity declaration (``manifest.identity_declarations``) and the vendored ``arn_formats.json``; it keeps no
table of types. These tests drive it over the real models and formats, and over a
small synthetic set where the rule itself is under test. Security Hub's use of it (``findings._asff_target``) is
covered here case by case and end to end in ``test_security_findings.py``. No AWS call is made.
"""

from __future__ import annotations

import json
import re
from typing import Any, ClassVar

import pytest

from tap_plugin.aws_core.collectors.boto3_collector import arn_resolver, iam_policy
from tap_plugin.aws_core.collectors.boto3_collector.arn_resolver import (
    ArnResolver,
    arn_keyed_types,
    declared_keys,
    default_resolver,
    other_id_keys,
    resolve_arn,
    resource_claimants,
)
from tap_plugin.aws_core.collectors.boto3_collector.identity import composite_natural_key, endpoint_key
from tap_plugin.aws_core.collectors.boto3_collector.manifest import identity_declarations
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
VOLUME_ARN = f"arn:{P}:ec2:{R}:{A}:volume/vol-0abc1234def567890"
SG_ARN = f"arn:{P}:ec2:{R}:{A}:security-group/sg-0abc1234def567890"
VPC_ARN = f"arn:{P}:ec2:{R}:{A}:vpc/vpc-0abc1234def567890"
SUBNET_ARN = f"arn:{P}:ec2:{R}:{A}:subnet/subnet-0abc1234def567890"
NACL_ARN = f"arn:{P}:ec2:{R}:{A}:network-acl/acl-0abc1234def567890"
DETECTOR_ARN = f"arn:{P}:guardduty:{R}:{A}:detector/12abc34d567e8fa901bc2d34e56789f0"
HOSTED_ZONE_ARN = f"arn:{P}:route53:::hostedzone/Z0123456789ABCDEFGHIJ"
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


def _sample_values(fmt: str) -> tuple[str, dict[str, str]]:
    """``_sample`` and the value it gave each named placeholder (a repeated placeholder keeps its first value)."""
    count = iter(range(1, 100))
    values: dict[str, str] = {}
    out: list[str] = []
    for index, segment in enumerate(fmt.split(":", 5)):
        if index == 1:
            out.append(P)
            continue
        if index in (3, 4) and _PLACEHOLDER.fullmatch(segment):
            value = (R if segment else "") if index == 3 else A
            if (name := _PLACEHOLDER.fullmatch(segment).group(1)) is not None:  # type: ignore[union-attr]
                values.setdefault(name, value)
            out.append(value)
            continue

        def token(match: re.Match[str]) -> str:
            value = f"v{next(count)}x"
            if match.group(1) is not None:
                values.setdefault(match.group(1), values.get(match.group(1)) or value)
            return value

        out.append(_PLACEHOLDER.sub(token, segment))
    return ":".join(out), values


def _expected_key(fields: tuple[str, ...], templates: dict[str, str], values: dict[str, str], arn: str) -> str:
    """The key a declaration's templates give for known placeholder values, rendered independently of the resolver."""
    parts = {
        name: arn if templates[name] == "@arn" else re.sub(r"\$\{(\w+)\}", lambda m: values[m.group(1)], templates[name])
        for name in fields
    }
    return parts[fields[0]] if len(fields) == 1 else composite_natural_key(parts)


def _shape(fmt: str) -> str:
    return _PLACEHOLDER.sub("{}", fmt)


def resolvability_census() -> dict[str, list[str]]:
    """Every aws_core type in exactly one bucket: what an ARN (or declared id) naming it resolves to, or why nothing
    does."""
    from tap_grid.registry import get_model_class, list_entity_types

    resolver = default_resolver()
    declarations = identity_declarations()
    by_arn = set(resolver.arn_keyed().values())
    by_key = {k.entity_type for k in resolver.declared().values()} | {
        t for t, d in declarations.items() if d.get("other_ids")
    }
    claims: dict[str, set[str]] = {}
    models = {t: get_model_class(t) for t in list_entity_types() if t.startswith("aws_core__")}
    for t, model in models.items():
        resource = getattr(model, "ARN_RESOURCE", None)
        if isinstance(resource, str):
            claims.setdefault(resource, set()).add(t)
    census: dict[str, list[str]] = {
        "by_arn": [], "by_declared_key": [], "no_arn_resource_type": [], "resource_type_shared": [],
        "key_not_in_arn": [], "pending_rekey": [],
    }
    for t, model in sorted(models.items()):
        resource = getattr(model, "ARN_RESOURCE", None)
        if t in by_arn:
            census["by_arn"].append(t)
        elif t in by_key:
            census["by_declared_key"].append(t)
        elif not isinstance(resource, str):
            census["no_arn_resource_type"].append(t)
        elif len(claims[resource]) > 1:
            census["resource_type_shared"].append(t)
        elif t in declarations:
            census["key_not_in_arn"].append(t)
        else:
            census["pending_rekey"].append(t)
    return census


class TestSecurityHubTarget:
    """``_asff_target``: what a Security Hub ``Resources[]`` entry points at. The ASFF ``Type`` is shown beside each
    id for readability; it plays no part (aws-core-tap#252)."""

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
        assert _asff_target(resource_id) == expected

    @pytest.mark.spec("req-aws-landing-zone-findings-2")
    @pytest.mark.parametrize(
        ("resource_type", "resource_id", "expected"),
        [
            ("AwsRdsDbCluster", RDS_CLUSTER_ARN, ("aws_core__aws_rds_db_cluster", RDS_CLUSTER_ARN)),
            ("AwsKmsKey", KMS_KEY_ARN, ("aws_core__aws_kms_key", KMS_KEY_ARN)),
            ("Other", KMS_KEY_ARN, ("aws_core__aws_kms_key", KMS_KEY_ARN)),
        ],
    )
    def test_any_arn_keyed_type_resolves_by_its_arn(self, resource_type: str, resource_id: str, expected: tuple) -> None:
        assert _asff_target(resource_id) == expected

    @pytest.mark.spec("req-aws-landing-zone-findings-2", "req-aws-collector-identity-12")
    @pytest.mark.parametrize(
        ("resource_type", "resource_id", "expected"),
        [
            # An EC2 instance is keyed by its id: the ARN resolves to it without the ASFF type saying so.
            ("Other", INSTANCE_ARN, ("aws_core__aws_ec2_instance", "i-0abc1234def567890")),
            ("AwsEc2Volume", VOLUME_ARN, ("aws_core__aws_ebs_volume", "vol-0abc1234def567890")),
            # An instance entry whose ARN is a volume's names the volume: the ARN alone says what it is.
            ("AwsEc2Instance", VOLUME_ARN, ("aws_core__aws_ebs_volume", "vol-0abc1234def567890")),
            ("AwsEc2SecurityGroup", SG_ARN, ("aws_core__aws_security_group", "sg-0abc1234def567890")),
            ("AwsEc2Vpc", VPC_ARN, ("aws_core__aws_vpc", "vpc-0abc1234def567890")),
            ("AwsEc2Subnet", SUBNET_ARN, ("aws_core__aws_subnet", "subnet-0abc1234def567890")),
            ("AwsEc2NetworkAcl", NACL_ARN, ("aws_core__aws_network_acl", "acl-0abc1234def567890")),
            # A template that keeps the prefix the key carries.
            ("Other", HOSTED_ZONE_ARN, ("aws_core__aws_route53_zone", "/hostedzone/Z0123456789ABCDEFGHIJ")),
            # A composite key, its account and region columns read from the ARN's own segments.
            (
                "AwsGuardDutyDetector",
                DETECTOR_ARN,
                (
                    "aws_core__aws_guardduty_detector",
                    composite_natural_key(
                        {"account_id": A, "region": R, "detector_id": "12abc34d567e8fa901bc2d34e56789f0"}
                    ),
                ),
            ),
            # Security Hub's account pseudo-id, through the account's declared other_ids.
            ("AwsAccount", f"AWS::::Account:{A}", ("aws_core__aws_account", A)),
        ],
    )
    def test_a_natively_keyed_type_resolves_through_its_declaration(
        self, resource_type: str, resource_id: str, expected: tuple
    ) -> None:
        assert _asff_target(resource_id) == expected

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
            # An account pseudo-id with nothing in the account's place.
            ("AwsAccount", "AWS::::Account:"),
            # A resource type four models share (the transit gateway attachment types).
            ("Other", f"arn:{P}:ec2:{R}:{A}:transit-gateway-attachment/tgw-attach-0abc"),
            # A detector ARN with no account: the key's account column cannot be filled, and the run's is never used.
            ("Other", f"arn:{P}:guardduty:{R}::detector/12abc"),
        ],
    )
    def test_an_unresolvable_id_names_nothing(self, resource_type: str, resource_id: str) -> None:
        assert _asff_target(resource_id) is None


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
    "x:declared": ["arn:${Partition}:x:${Region}:${Account}:declared/d-${DeclaredId}"],
    "x:scoped": ["arn:${Partition}:x:${Region}:${Account}:scoped/${ScopedId}"],
    "x:partial": ["arn:${Partition}:x:${Region}:${Account}:partial/${PartialId}"],
    "x:shared": ["arn:${Partition}:x:${Region}:${Account}:shared/${SharedId}"],
    "x:whole": ["arn:${Partition}:x::${Account}:whole/${WholeName}"],
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


class TestDeclaredKeys:
    """The resolver reads a natively keyed type's key from the ARN through its identity declaration
    (aws-core-tap#252, ``req-aws-collector-identity-12``)."""

    MODELS: ClassVar[list[type]] = [
        TestTheRule._model("declared", "x:declared", ("declared_id",)),
        TestTheRule._model("scoped", "x:scoped", ("account_id", "region", "scoped_id")),
        TestTheRule._model("partial", "x:partial", ("store_id", "partial_id")),
        TestTheRule._model("shared_by_arn", "x:shared", ("arn",)),
        TestTheRule._model("shared_by_id", "x:shared", ("shared_id",)),
        TestTheRule._model("whole", "x:whole", ("serial_number",)),
        TestTheRule._model("undeclared", "x:byid", ("byid_id",)),
        TestTheRule._model("account", None, ("account_id",)),
    ]
    DECLARATIONS: ClassVar[dict[str, dict[str, Any]]] = {
        "declared": {"cfn_type": "AWS::X::Declared", "key": {"declared_id": "Id"}, "arn_key": {"declared_id": "d-${DeclaredId}"}},
        "scoped": {
            "cfn_type": "AWS::X::Scoped",
            "key": {"account_id": "@account", "region": "@region", "scoped_id": "Id"},
            "arn_key": {"account_id": "${Account}", "region": "${Region}", "scoped_id": "${ScopedId}"},
        },
        # The ARN does not carry the store id, so there is no arn_key to read the key from.
        "partial": {"cfn_type": "AWS::X::Partial", "key": {"store_id": "StoreId", "partial_id": "Id"}},
        "shared_by_id": {"cfn_type": "AWS::X::Shared", "key": {"shared_id": "Id"}, "arn_key": {"shared_id": "${SharedId}"}},
        "whole": {"cfn_type": "AWS::X::Whole", "key": {"serial_number": "SerialNumber"}, "arn_key": {"serial_number": "@arn"}},
        "account": {
            "cfn_type": "AWS::X::Account",
            "key": {"account_id": "AccountId"},
            "arn_key": {"account_id": "${AccountId}"},
            "other_ids": ["AWS::::Account:${AccountId}"],
        },
    }

    def _resolver(self) -> ArnResolver:
        return ArnResolver(
            SYNTHETIC_FORMATS,
            arn_keyed_types(self.MODELS),
            declared_keys(self.MODELS, self.DECLARATIONS),
            other_id_keys(self.MODELS, self.DECLARATIONS),
        )

    def test_a_single_field_key_is_read_through_its_template(self) -> None:
        assert self._resolver().resolve(f"arn:{P}:x:{R}:{A}:declared/d-123") == ("declared", "d-123")

    def test_a_composite_key_takes_its_account_and_region_from_the_arns_own_segments(self) -> None:
        # The resolver has no run scope to fall back on: whatever the ARN says is what the key gets.
        resolved = self._resolver().resolve(f"arn:aws-us-gov:x:us-gov-east-1:{A}:scoped/s-9")
        assert resolved == ("scoped", composite_natural_key({"account_id": A, "region": "us-gov-east-1", "scoped_id": "s-9"}))

    def test_an_empty_account_or_region_segment_leaves_the_arn_unresolved(self) -> None:
        resolver = self._resolver()
        assert resolver.resolve(f"arn:{P}:x::{A}:scoped/s-9") is None
        assert resolver.resolve(f"arn:{P}:x:{R}::scoped/s-9") is None

    def test_a_model_naming_the_resource_type_makes_it_ambiguous_however_it_is_keyed(self) -> None:
        # A second model on x:declared keyed by a house string has no arn_key, but it is still a claimant: the ARN
        # cannot say which of the two it is (PR 254 review).
        house = type("M", (), {"ENTITY_TYPE": "house", "ARN_RESOURCE": "x:declared", "NATURAL_KEY": ("house_key",)})
        models = [*self.MODELS, house]
        resolver = ArnResolver(
            SYNTHETIC_FORMATS,
            arn_keyed_types(models),
            declared_keys(models, self.DECLARATIONS),
            other_id_keys(models, self.DECLARATIONS),
            resource_claimants(models),
        )
        assert resolver.resolve(f"arn:{P}:x:{R}:{A}:declared/d-123") is None
        assert self._resolver().resolve(f"arn:{P}:x:{R}:{A}:declared/d-123") == ("declared", "d-123")

    def test_a_key_the_arn_does_not_carry_names_nothing(self) -> None:
        assert self._resolver().resolve(f"arn:{P}:x:{R}:{A}:partial/p-1") is None

    def test_a_resource_type_claimed_by_arn_and_by_declaration_names_nothing(self) -> None:
        assert self._resolver().resolve(f"arn:{P}:x:{R}:{A}:shared/s-1") is None

    def test_a_field_holding_the_whole_arn_is_the_arn(self) -> None:
        arn = f"arn:{P}:x::{A}:whole/ops/token"
        assert self._resolver().resolve(arn) == ("whole", arn)

    def test_an_undeclared_id_keyed_type_names_nothing(self) -> None:
        assert self._resolver().resolve(f"arn:{P}:x:{R}:{A}:byid/b-1") is None

    def test_a_declared_other_id_resolves_without_an_arn(self) -> None:
        resolver = self._resolver()
        assert resolver.resolve(f"AWS::::Account:{A}") == ("account", A)
        assert resolver.resolve("AWS::::Account:") is None
        assert resolver.resolve(f"AWS::::Region:{R}") is None

    def test_only_declared_and_arn_keyed_types_are_targets(self) -> None:
        # shared_by_arn and shared_by_id cancel out; partial has no arn_key; undeclared declares nothing.
        assert self._resolver().targets() == {"declared", "scoped", "whole", "account"}

    def test_a_composite_key_names_its_node_as_an_endpoint_by_every_part(self) -> None:
        """The composite key string the resolver writes is the one an edge endpoint splits back exactly
        (``identity.endpoint_key``), so an edge to a node the batch does not carry is named by its full key."""
        key = {"account_id": A, "region": R, "detector_id": "d1"}
        endpoint = endpoint_key("aws_core__aws_guardduty_detector", composite_natural_key(key))
        assert endpoint == {"entity_type": "aws_core__aws_guardduty_detector", "key": key}


class TestOverTheRealModels:
    """The resolver built from the registry and ``arn_formats.json``."""

    def test_it_reads_the_same_vendored_file_as_the_refresh(self) -> None:
        assert arn_resolver.ARN_FORMATS == iam_policy.ARN_FORMATS

    @pytest.mark.spec("req-aws-landing-zone-findings-2")
    def test_the_resolver_names_only_aws_core_types(self) -> None:
        """The Security Hub CONCERNS_RESOURCE target is open in the schema (aws-build Q90a); what keeps it
        to aws_core nodes is the resolver, built over this plugin's models only."""
        targets = default_resolver().targets()
        assert len(targets) > 700
        foreign = sorted(t for t in targets if not t.startswith("aws_core__"))
        assert not foreign, foreign

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

    @pytest.mark.spec("req-aws-landing-zone-findings-2", "req-aws-collector-identity-12")
    def test_every_declared_type_resolves_its_own_arn_to_its_key(self) -> None:
        """For each natively keyed type whose declaration says how to read its key from the ARN, and whose resource
        type no other model claims, an ARN built from each of its formats resolves to the key the declaration's
        templates give (rendered here independently of the resolver). The exception is again a format another
        resource type shares the shape of."""
        resolver = default_resolver()
        declared = resolver.declared()
        assert len(declared) > 80
        resolved = 0
        for resource, key in declared.items():
            for fmt in FORMATS[resource]:
                arn, values = _sample_values(fmt)
                if resolver.resource_of(arn) != resource:
                    rivals = [o for o, fs in FORMATS.items() if o != resource and any(_shape(f) == _shape(fmt) for f in fs)]
                    assert rivals, f"{arn} ({resource}) does not match its own format, and no other resource type has its shape"
                    continue
                assert resolve_arn(arn) == (key.entity_type, _expected_key(key.fields, dict(key.templates), values, arn)), resource
                resolved += 1
        assert resolved > 80

    @pytest.mark.spec("req-aws-landing-zone-findings-2", "req-aws-collector-identity-12")
    def test_every_type_is_counted_resolvable_or_not_and_why(self) -> None:
        """aws-core-tap#249: a census of every aws_core type: resolved by its ARN, by its declared key, or not at all,
        and for the last why. The id-keyed EC2 types the GovCloud trial left unlinked, the GuardDuty detector and the
        account are in the resolvable set; the numbers only grow."""
        census = resolvability_census()
        counts = {bucket: len(types) for bucket, types in census.items()}
        assert sum(counts.values()) > 900
        assert counts["by_arn"] > 600
        assert counts["by_declared_key"] > 80
        for short in ("vpc", "subnet", "security_group", "network_acl", "ebs_volume", "ec2_instance", "guardduty_detector", "account"):
            assert f"aws_core__aws_{short}" in census["by_declared_key"], short

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
