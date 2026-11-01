"""Named listing outcomes and the request/client fixes found by the 2026-11-01 GovCloud wave-0 run.

Covers ``req-aws-collector-outcome`` (``not_configured``, ``unsupported_in_partition``, ``throttled``: data-driven,
never a broad catch, never an authoritative empty listing) and ``req-aws-collector-client`` (one Config for the
timeouts and retry posture), plus the three manifest source fixes (VPC BPA exclusion ``MaxResults``, IoT SiteWise
assets per model, the AWS-owned EventSchemas registry).
"""

from __future__ import annotations

import copy
import uuid

import jsonschema
import pytest
from botocore.exceptions import ClientError, ConnectTimeoutError, EndpointConnectionError, ReadTimeoutError
from tap_cares.collectors.config import CollectorConfig
from tap_cares.secrets.models import Secret, SecretRef

from tap_plugin.aws_core.collectors.boto3_collector import collector as collector_mod
from tap_plugin.aws_core.collectors.boto3_collector import credentials as cred
from tap_plugin.aws_core.collectors.boto3_collector import outcomes
from tap_plugin.aws_core.collectors.boto3_collector.collector import Boto3Collector
from tap_plugin.aws_core.collectors.boto3_collector.containment import Listing, surface_of
from tap_plugin.aws_core.collectors.boto3_collector.listing import ListingWalk, surface_statement
from tap_plugin.aws_core.collectors.boto3_collector.manifest import manifest_entries
from tap_plugin.aws_core.collectors.boto3_collector.regions import STATUS_ENABLED, RegionFacts
from tap_plugin.aws_core.collectors.boto3_collector.source import CustomFnRegistry, iter_source

_ACCOUNT = "111122223333"
_REGION = "us-gov-west-1"
_GOV = "aws-us-gov"


def _entry(entity: str) -> dict:
    return next(e for e in manifest_entries() if e["entity_type"] == f"aws_core__aws_{entity}")


def _client_error(code: str, operation: str, message: str = "boom") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": message}}, operation)


class TestTheShippedRows:
    def test_the_file_loads_and_validates(self):
        assert len(outcomes.load_rows()) > 20

    def test_every_row_carries_a_reason(self):
        for row in outcomes.load_rows():
            assert len(row["why"]) >= 20, row

    def test_a_not_configured_row_is_never_a_broad_catch(self):
        for row in outcomes.load_rows():
            if row["outcome"] == "not_configured":
                assert row["service"] != "*", row
                assert "error_code" in row, row
                assert row.get("operations") or row.get("entity_types"), row

    def test_the_schema_refuses_a_broad_not_configured_row(self):
        schema = outcomes.load_schema(outcomes.OUTCOMES_SCHEMA_PATH)
        validator = jsonschema.Draft202012Validator(schema)
        good = {
            "outcome": "not_configured",
            "service": "drs",
            "operations": ["DescribeSourceNetworks"],
            "error_code": "UninitializedAccountException",
            "why": "the account has not been initialised for this service",
        }
        assert validator.is_valid({"description": "d", "rows": [good]})
        for broken in (
            {k: v for k, v in good.items() if k != "operations"},
            {k: v for k, v in good.items() if k != "error_code"},
            {**good, "service": "*"},
            {k: v for k, v in good.items() if k != "why"},
        ):
            assert not validator.is_valid({"description": "d", "rows": [broken]}), broken

    def test_an_unsupported_row_must_say_where_it_does_not_apply(self):
        schema = outcomes.load_schema(outcomes.OUTCOMES_SCHEMA_PATH)
        row = {"outcome": "unsupported_in_partition", "service": "*", "error_code": "InvalidAction", "why": "x" * 25}
        assert not jsonschema.Draft202012Validator(schema).is_valid({"description": "d", "rows": [row]})


class TestClassify:
    def test_each_reported_not_configured_case_is_recognised(self):
        cases = [
            ("drs_source_network", "UninitializedAccountException", "DescribeSourceNetworks"),
            ("mgn_wave", "UninitializedAccountException", "ListWaves"),
            ("s3_access_grant", "AccessGrantsInstanceNotExistsError", "ListAccessGrants"),
            ("quicksight_dashboard", "UnsupportedUserEditionException", "ListDashboards"),
            ("quicksight_space", "PreconditionNotMetException", "ListSpaces"),
            ("quicksight_vpc_connection", "ResourceNotFoundException", "ListVPCConnections"),
            ("securityhub_hub_v2", "ResourceNotFoundException", "DescribeSecurityHubV2"),
            ("securityhub_aggregator_v2", "ConflictException", "ListAggregatorsV2"),
            ("securitylake_subscriber", "ResourceNotFoundException", "ListSubscribers"),
        ]
        for entity, code, operation in cases:
            message = {"ListAggregatorsV2": "Security Hub V2 is not enabled", "ListSubscribers": "Security Lake isn't enabled"}.get(
                operation, "x"
            )
            found = outcomes.classify(_entry(entity), _client_error(code, operation, message), _GOV)
            assert found is not None and found.kind == "not_configured", (entity, found)
            assert found.code == code

    def test_the_same_code_on_another_operation_is_still_an_error(self):
        # ResourceNotFoundException is only "not configured" where a row names the operation.
        assert outcomes.classify(_entry("drs_source_network"), _client_error("ResourceNotFoundException", "DescribeSourceNetworks"), _GOV) is None
        assert outcomes.classify(_entry("quicksight_dashboard"), _client_error("ResourceNotFoundException", "ListDashboards"), _GOV) is None

    def test_a_row_for_one_service_does_not_cover_another(self):
        # DRS's code on a MGN-shaped operation name of a different service entry is not matched.
        assert outcomes.classify(_entry("vpc"), _client_error("UninitializedAccountException", "DescribeVpcs"), _GOV) is None

    def test_a_generic_code_needs_its_message(self):
        entry = _entry("securityhub_aggregator_v2")
        assert outcomes.classify(entry, _client_error("ConflictException", "ListAggregatorsV2", "Security Hub V2 is not enabled for 1"), _GOV)
        assert outcomes.classify(entry, _client_error("ConflictException", "ListAggregatorsV2", "a concurrent change"), _GOV) is None

    def test_access_denied_is_not_classified(self):
        assert outcomes.classify(_entry("drs_source_network"), _client_error("AccessDeniedException", "DescribeSourceNetworks"), _GOV) is None

    def test_an_unreachable_endpoint_is_unsupported_outside_commercial_only(self):
        entry = _entry("qbusiness_application")
        exc = EndpointConnectionError(endpoint_url="https://qbusiness.us-gov-west-1.api.aws/applications")
        found = outcomes.classify(entry, exc, _GOV)
        assert found is not None and found.kind == "unsupported_in_partition"
        assert outcomes.classify(entry, exc, "aws") is None  # commercial offers it: a real failure there

    def test_a_connect_timeout_is_not_called_unsupported(self):
        # A timeout means the endpoint was unreachable, not that the service is absent: a transient fault reads the same.
        # It stays a failed call (bounded by the client's connect timeout), and is never read as empty or unsupported.
        timeout = ConnectTimeoutError(endpoint_url="https://inspector.us-gov-west-1.amazonaws.com")
        assert outcomes.classify(_entry("inspector_assessment_target"), timeout, _GOV) is None

    def test_a_read_timeout_is_not_an_unsupported_endpoint(self):
        exc = ReadTimeoutError(endpoint_url="https://x")
        assert outcomes.classify(_entry("qbusiness_application"), exc, _GOV) is None

    @pytest.mark.parametrize(
        ("code", "operation", "message"),
        [
            ("UnknownOperationException", "ListClusters", "The requested operation is not supported in the called region."),
            ("InvalidAction", "DescribeRouteServers", "not valid for this web service"),
            ("UnsupportedOperation", "DescribeCarrierGateways", "not available in this region"),
            ("404", "ListStreams", "No method found matching route."),
            ("404", "ListApplications", "Unknown Operation"),
            ("InvalidRequestException", "ListFlywheels", "UNSUPPORTED_OPERATION: This operation is not supported in this region"),
            ("ValidationException", "ListProfiles", "[Validation] This operation is not supported in GovCloud."),
        ],
    )
    def test_the_unknown_operation_family_is_unsupported_in_the_partition(self, code, operation, message):
        found = outcomes.classify(_entry("vpc"), _client_error(code, operation, message), _GOV)
        assert found is not None and found.kind == "unsupported_in_partition", found

    def test_an_unmatched_message_on_a_generic_code_is_an_error(self):
        assert outcomes.classify(_entry("vpc"), _client_error("InvalidRequestException", "ListX", "bad parameter"), _GOV) is None
        assert outcomes.classify(_entry("vpc"), _client_error("ValidationException", "ListX", "Bad Request"), _GOV) is None

    def test_throttling_is_its_own_named_outcome(self):
        found = outcomes.classify(_entry("athena_capacity_reservation"), _client_error("ThrottlingException", "ListCapacityReservations"), _GOV)
        assert found is not None and found.kind == "throttled"

    def test_a_non_aws_exception_is_nothing(self):
        assert outcomes.classify(_entry("vpc"), RuntimeError("x"), _GOV) is None


class TestCompletenessConsequence:
    """A named non-failure outcome yields zero rows and must license nothing (tap_grid.completeness)."""

    _FACTS = RegionFacts(_REGION, _GOV, "opt-in-not-required", STATUS_ENABLED, "enabled")

    def _surface(self, listing: Listing) -> dict:
        return surface_of(relation="r", edge_type="E", subject="s", facts=self._FACTS, listing=listing)

    def test_an_empty_listing_in_an_enabled_region_is_complete(self):
        listing = Listing()
        listing.count = 0
        surface = self._surface(listing)
        assert surface["enumeration_complete"] is True and surface["count_observed"] == 0

    def test_not_configured_is_not_a_complete_empty_observation(self):
        listing = Listing()
        listing.outcome = outcomes.Outcome("not_configured", "UninitializedAccountException", "never initialised")
        surface = self._surface(listing)
        assert surface["enumeration_complete"] is False
        assert surface["admitted"] is False
        assert surface["count_observed"] is None
        assert surface["scope_authorized"] is True  # the credential was allowed to ask and was answered
        assert surface["reasons"]["enumeration_complete"].startswith("not_configured: UninitializedAccountException")
        assert "admitted" in surface["reasons"]

    @pytest.mark.parametrize("kind", ["unsupported_in_partition", "throttled"])
    def test_the_other_outcomes_are_not_complete_and_not_authorized_either(self, kind):
        listing = Listing()
        listing.outcome = outcomes.Outcome(kind, "X", "why")
        surface = self._surface(listing)
        assert surface["enumeration_complete"] is False
        assert surface["scope_authorized"] is None
        assert "scope_authorized" in surface["reasons"]

    def test_an_account_scoped_walk_is_not_complete_either(self):
        walk = ListingWalk()
        walk.not_observed("not_configured", "not_configured: AccessGrantsInstanceNotExistsError: no instance", authorized=True)
        surface = surface_statement(walk, relation="r", edge_type="E", subject="s", applied_batches=["b"])
        assert surface["enumeration_complete"] is False
        assert surface["admitted"] is False
        assert surface["scope_authorized"] is True
        assert surface["reasons"]["enumeration_complete"].startswith("not_configured")
        assert "scope_authorized" not in surface["reasons"]


# --- collector.run() end to end ---------------------------------------------------------------


class _Raising:
    """A client whose list calls raise ``exc``; counts the calls."""

    def __init__(self, exc: Exception, counter: list[str]) -> None:
        self._exc = exc
        self._counter = counter

    def can_paginate(self, _method: str) -> bool:
        return False

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)

        def call(**_kw):
            self._counter.append(name)
            raise self._exc

        return call


class _NoPages:
    def paginate(self, **_kw):
        return []


class _Canned:
    def can_paginate(self, _method: str) -> bool:
        return False

    def get_paginator(self, _name: str) -> _NoPages:
        return _NoPages()

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        answers = {
            "describe_regions": {"Regions": [{"RegionName": _REGION, "OptInStatus": "opt-in-not-required"}]},
            "get_caller_identity": {"Account": _ACCOUNT},
        }
        return lambda **_kw: answers.get(name, {})


class _Events:
    def register(self, _name: str, _handler: object) -> None:
        return None


class _Session:
    events = _Events()

    def client(self, _service: str, **_kw: object) -> _Canned:
        return _Canned()


@pytest.fixture
def _run_with(monkeypatch):
    secret = Secret(
        ref=SecretRef(scope="aws_core", key="boto_collector"),
        kind="aws_static_access_key",
        description="test",
        data={"access_key_id": "AKIA", "secret_access_key": "shh", "regions_allowed": [_REGION]},
        metadata={},
        source_path=__import__("pathlib").Path("/dev/null"),
    )
    monkeypatch.setattr(cred, "resolve_secret", lambda _ref: secret)
    monkeypatch.setattr(collector_mod, "build_session", lambda _data: _Session())
    monkeypatch.setattr(collector_mod, "caller_account_id", lambda *a, **k: _ACCOUNT)

    def run(failures: dict[str, Exception]) -> tuple[Boto3Collector, list[str]]:
        calls: list[str] = []
        monkeypatch.setattr(
            collector_mod,
            "client_factory",
            lambda _s, _region: (lambda service: _Raising(failures[service], calls) if service in failures else _Canned()),
        )
        collector = Boto3Collector(
            CollectorConfig(collector_entity_id=uuid.uuid7(), collection_job_entity_id=uuid.uuid7())
        )
        collector.run()
        assert collector.results["error"] == []
        return collector, calls

    return run


def _codes(collector: Boto3Collector, level: str) -> list[str]:
    return [r["message_code"] for r in collector.results[level]]


def _vpc_surface(collector: Boto3Collector) -> dict:
    found = [s for s in collector._surfaces if s["relation"] == "account_region.vpcs"]
    assert len(found) == 1
    return found[0]


@pytest.mark.django_db
class TestCollectorRun:
    def test_a_mapped_error_is_empty_plus_an_info_and_not_a_complete_listing(self, _run_with, monkeypatch):
        row = {
            "outcome": "not_configured",
            "service": "ec2",
            "operations": ["DescribeVpcs"],
            "error_code": "NotConfiguredForTest",
            "why": "a test row: the account has not set this up",
        }
        shipped = outcomes.load_rows()
        monkeypatch.setattr(outcomes, "load_rows", lambda: (*shipped, row))
        collector, _calls = _run_with({"ec2": _client_error("NotConfiguredForTest", "DescribeVpcs", "not set up")})
        infos = [r for r in collector.results["info"] if r["message_code"] == "ENTRY_NOT_CONFIGURED"]
        assert any(r["message_data"]["entity_type"] == "aws_core__aws_vpc" for r in infos), infos
        assert not [
            w for w in collector.results["warn"] if w["message_code"] == "ENTRY_SKIPPED" and "aws_vpc " in w["message"]
        ]
        surface = _vpc_surface(collector)
        assert surface["enumeration_complete"] is False
        assert surface["reasons"]["enumeration_complete"].startswith("not_configured: NotConfiguredForTest")
        assert "not configured" in collector.summary

    def test_an_unmapped_error_still_fails_as_before(self, _run_with):
        collector, _calls = _run_with({"ec2": _client_error("SomethingElseEntirely", "DescribeVpcs", "no")})
        assert "ENTRY_NOT_CONFIGURED" not in _codes(collector, "info")
        skips = [w for w in collector.results["warn"] if w["message_code"] == "ENTRY_SKIPPED" and "aws_vpc" in w["message"]]
        assert skips
        surface = _vpc_surface(collector)
        assert surface["enumeration_complete"] is not True
        assert surface["reasons"]["enumeration_complete"].startswith("listing_failed")

    def test_a_throttled_listing_is_a_named_warning_and_not_an_empty_one(self, _run_with):
        collector, _calls = _run_with({"ec2": _client_error("ThrottlingException", "DescribeVpcs", "Rate exceeded")})
        throttled = [w for w in collector.results["warn"] if w["message_code"] == "ENTRY_THROTTLED"]
        assert any(w["message_data"]["entity_type"] == "aws_core__aws_vpc" for w in throttled)
        surface = _vpc_surface(collector)
        assert surface["enumeration_complete"] is False
        assert surface["reasons"]["enumeration_complete"].startswith("throttled: ThrottlingException")

    def test_an_unreachable_service_is_learned_once_not_once_per_entry(self, _run_with):
        exc = EndpointConnectionError(endpoint_url="https://qbusiness.us-gov-west-1.api.aws/applications")
        collector, calls = _run_with({"qbusiness": exc})
        entries = [e["entity_type"] for e in manifest_entries() if e["service"] == "qbusiness"]
        assert len(entries) > 2
        info = [r for r in collector.results["info"] if r["message_code"] == "SERVICE_NOT_AVAILABLE_IN_PARTITION"]
        assert {r["message_data"]["entity_type"] for r in info} >= set(entries)
        assert all(r["message_data"]["outcome"] == "unsupported_in_partition" for r in info if r["message_data"]["service"] == "qbusiness")
        assert len([c for c in calls if c == "list_applications"]) == 1
        assert not [w for w in collector.results["warn"] if w["message_code"] == "ENTRY_SKIPPED" and "qbusiness" in w["message"]]


class TestClientConfig:
    def test_one_config_sets_the_timeouts_and_a_finite_adaptive_retry_budget(self):
        config = cred.client_config()
        assert config.connect_timeout == cred.CONNECT_TIMEOUT_SECONDS == 5
        assert config.read_timeout == cred.READ_TIMEOUT_SECONDS == 60
        assert config.retries == {"mode": "adaptive", "max_attempts": 8}
        # The worst case of an endpoint that never answers: every attempt waits out the connect timeout.
        assert config.retries["max_attempts"] * config.connect_timeout <= 60

    def test_the_client_factory_builds_every_client_with_it(self):
        seen: list[dict] = []

        class Session:
            def client(self, service, **kw):
                seen.append({"service": service, **kw})
                return object()

        cred.client_factory(Session(), _REGION)("inspector")
        assert seen[0]["region_name"] == _REGION
        assert seen[0]["config"].connect_timeout == 5 and seen[0]["config"].retries["mode"] == "adaptive"

    def test_a_session_carries_it_as_its_default_so_a_custom_fn_client_has_it_too(self):
        session = cred._botocore_session(None)
        default = session.get_default_client_config()
        assert default.connect_timeout == 5 and default.read_timeout == 60
        assert default.retries == {"mode": "adaptive", "max_attempts": 8}

    def test_no_collector_module_builds_its_own_retry_config(self):
        import pathlib

        root = pathlib.Path(collector_mod.__file__).parent
        offenders = [
            p.name
            for p in root.glob("*.py")
            if "Config(" in p.read_text().replace("CollectorConfig(", "").replace("client_config(", "") and p.name != "credentials.py"
        ]
        assert offenders == []


# --- the manifest source fixes -----------------------------------------------------------------


class _Calls:
    """A client that answers by method and arguments, remembers the calls, and can refuse like AWS."""

    def __init__(self, answers):
        self._answers = answers
        self.calls: list[tuple[str, dict]] = []

    def can_paginate(self, _method):
        return False

    def __getattr__(self, name):
        if name.startswith("_") or name not in self._answers:
            raise AttributeError(name)

        def call(**kw):
            self.calls.append((name, kw))
            answer = self._answers[name]
            return answer(**kw) if callable(answer) else answer

        return call


def _items(entity: str, client) -> list:
    entry = _entry(entity)
    return list(
        iter_source(
            entry,
            client_for=lambda _s: client,
            custom_fns=CustomFnRegistry(),
            account_id=_ACCOUNT,
            scope={"partition": _GOV, "region": _REGION, "account": _ACCOUNT},
        )
    )


class TestRequestFixes:
    def test_vpc_block_public_access_exclusions_send_max_results(self):
        def answer(**kw):
            if "MaxResults" not in kw and "ExclusionIds" not in kw:
                raise _client_error("MissingParameter", "DescribeVpcBlockPublicAccessExclusions")
            return {"VpcBlockPublicAccessExclusions": [{"ExclusionId": "vpcbpa-1"}]}

        client = _Calls({"describe_vpc_block_public_access_exclusions": answer})
        assert [i["ExclusionId"] for i in _items("ec2_vpc_block_public_access_exclusion", client)] == ["vpcbpa-1"]
        assert 5 <= client.calls[0][1]["MaxResults"] <= 1000

    def test_iotsitewise_assets_are_listed_per_asset_model(self):
        def assets(**kw):
            if "assetModelId" not in kw:
                raise _client_error("InvalidRequestException", "ListAssets", "AssetModelID is required when listing ALL assets.")
            return {"assetSummaries": [{"arn": f"arn:aws-us-gov:iotsitewise:::asset/{kw['assetModelId']}-a", "name": "a"}]}

        client = _Calls(
            {
                "list_asset_models": {"assetModelSummaries": [{"id": "m1"}, {"id": "m2"}]},
                "list_assets": assets,
            }
        )
        items = _items("iotsitewise_asset", client)
        assert [i["arn"].rsplit("/", 1)[1] for i in items] == ["m1-a", "m2-a"]
        by_name = {name: kw for name, kw in client.calls}
        assert by_name["list_asset_models"]["assetModelTypes"] == ["ASSET_MODEL"]
        assert [kw["assetModelId"] for name, kw in client.calls if name == "list_assets"] == ["m1", "m2"]
        assert all(kw["filter"] == "ALL" for name, kw in client.calls if name == "list_assets")

    def test_the_aws_owned_registry_is_not_read_as_the_accounts(self):
        registries = {
            "Registries": [
                {"RegistryName": "aws.events"},  # AWS-owned: no RegistryArn
                {"RegistryName": "mine", "RegistryArn": "arn:aws-us-gov:schemas:us-gov-west-1:1:registry/mine"},
            ]
        }
        client = _Calls({"list_registries": registries})
        assert [r["RegistryName"] for r in _items("eventschemas_registry", client)] == ["mine"]

    def test_the_schemas_of_the_aws_owned_registry_are_not_listed(self):
        def schemas(**kw):
            return {"Schemas": [{"SchemaName": "s", "SchemaArn": f"arn:x:schema/{kw['RegistryName']}/s"}]}

        client = _Calls(
            {
                "list_registries": {"Registries": [{"RegistryName": "aws.events"}, {"RegistryName": "mine"}]},
                "list_schemas": schemas,
            }
        )
        items = _items("eventschemas_schema", client)
        assert [i["SchemaArn"] for i in items] == ["arn:x:schema/mine/s"]
        assert [kw["RegistryName"] for name, kw in client.calls if name == "list_schemas"] == ["mine"]

    def test_not_prefix_keeps_a_non_matching_value_and_the_schema_takes_it(self):
        from tap_plugin.aws_core.collectors.boto3_collector.source import _passes

        assert _passes({"n": "mine"}, [{"path": "n", "not_prefix": "aws."}])
        assert not _passes({"n": "aws.events"}, [{"path": "n", "not_prefix": "aws."}])
        entry = copy.deepcopy(_entry("eventschemas_registry"))
        assert entry["source"]["where"] == [{"path": "RegistryName", "not_prefix": "aws."}]
        assert "aws." in entry["why"] and "AWS-owned" in entry["why"]
