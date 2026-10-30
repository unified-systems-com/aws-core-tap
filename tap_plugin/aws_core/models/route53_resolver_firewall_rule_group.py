"""Route 53 Resolver DNS Firewall rule group — the DNS query filter applied to associated VPCs."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel

_NAME_LIST = {"type": "array", "items": {"type": "string", "minLength": 1}}


class Route53ResolverFirewallRuleGroup(BaseModel):
    """A Route 53 Resolver DNS Firewall rule group.

    Each rule pairs a domain list with an action. The rules are summarised as three typed lists of
    domain-list names, one per action, rather than stored as a rule blob. Source:
    ``route53resolver:ListFirewallRules`` (``FirewallDomainListId``, ``Action``) joined to
    ``GetFirewallDomainList`` (``Name``; AWS-managed lists carry AWS's own name, e.g.
    ``AWSManagedDomainsMalwareDomainList``). The VPCs it filters are ``FILTERS_VPC_DNS`` edges, one
    per ``FirewallRuleGroupAssociation``. Design vocabulary: no collector emits it yet.

    Spec: specs/spec-aws-core-v0.md (req-aws-core-dns-firewall)
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_route53_resolver_firewall_rule_group"
    ENTITY_NAME: ClassVar[str] = "Route 53 Resolver DNS Firewall Rule Group"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "A Route 53 Resolver DNS Firewall rule group: domain lists to block, allow or alert on, "
        "applied to the DNS queries of the VPCs it is associated with."
    )
    ENTITY_ICON: ClassVar[str] = "aws-route53"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#DAD1E6", "border": "#7B5EA7", "label": "#221A2E"},
        }
    }

    # AWS's rule group id (rslvr-frg-…).
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("rule_group_id",)

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "rule_group_id": {"type": "string", "pattern": "^(rslvr-frg-[0-9a-z]{8,32})?$"},
        "rule_count": {"type": ["integer", "null"], "minimum": 0},
        "block_domain_lists": _NAME_LIST,
        "allow_domain_lists": _NAME_LIST,
        "alert_domain_lists": _NAME_LIST,
        "region": {"type": "string"},
        "tags": {"type": ["object", "null"], "additionalProperties": {"type": "string"}},
        "configuration": {"type": "object"},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }

    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=64, blank=True, default="")
    rule_group_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    rule_count = models.IntegerField(null=True, blank=True, default=None)
    # Domain-list names by rule action (BLOCK / ALLOW / ALERT). Empty means no rule with that action.
    block_domain_lists = models.JSONField(default=list, blank=True)
    allow_domain_lists = models.JSONField(default=list, blank=True)
    alert_domain_lists = models.JSONField(default=list, blank=True)
    region = models.CharField(max_length=32, blank=True, default="")
    # AWS tags, canonical flat {str: str} (req-aws-core-fields-4). Source: route53resolver:ListTagsForResource.
    tags = models.JSONField(null=True, blank=True, default=None)
    # The collector's configuration envelope; {} when the manifest entry does not persist it.
    configuration = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_route53_resolver_firewall_rule_group"

    def get_name(self) -> str:
        return self.name or self.rule_group_id

    def __str__(self) -> str:
        return self.get_name()
