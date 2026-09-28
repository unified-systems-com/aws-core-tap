"""The regional-containment table: which collected types an account's region footprint contains.

One row per child type. This is the single place the *shape* of region-scoped containment is
written down in code; everything that must agree with it is checked against it by
``tests/test_regional_containment.py`` rather than re-derived by hand (the ``.edge.json`` files,
the manifest entries' ``containment`` blocks, the ``[falsifiers]`` table, and the parent
model's ``OUTBOUND_EDGES`` / ``CONTAINMENT_EDGES``).

Why one edge type per child type, not one ``HOSTS`` edge over all of them. The completeness
surface a collector records names the listing it read (``ec2:DescribeVpcs`` in one region) and the
grid edge type that listing maps to. Candidate derivation
(``tap_grid.candidates._children``) then fans out over **every** live edge of that type from the
parent: it cannot tell an instance from a VPC by target type. With one shared edge type, a
complete VPC listing would make every instance under the same footprint a retirement candidate
whether or not the instance listing ran to the end. One edge type per listing keeps the
completeness claim and the fan-out the same set.

**Why only four rows today (tap-plugin-aws-core#49), not the full regional surface.**
``tap_plugins/validate/service.py::_check_falsifier_coverage`` (a ``loads``-level check every
plugin repo's CI runs under ``--strict``) reads every model's ``CONTAINMENT_EDGES`` and warns —
promoted to a hard failure by ``--strict`` — on any declared target with no ``[falsifiers]`` row.
A row here becomes a target of ``AwsAccountRegion.CONTAINMENT_EDGES``
(see ``models/aws_account_region.py``), so a row for a type with no registered falsifier would red
that gate the moment this ships. VPC, subnet, EC2 instance and security group are the four types
``VpcFalsifier`` / ``SubnetFalsifier`` / ``Ec2InstanceFalsifier`` / ``SecurityGroupFalsifier``
(tap-plugin-aws-core#44) already cover — this PR supplies the containment substrate those
falsifiers have been sitting without; nothing else needs to change on that side for them to start
producing real candidates once both PRs are on main. Route table, internet gateway, NAT gateway,
network ACL, Elastic IP, VPC endpoint, EBS volume and RDS instance are all region-scoped and
belong in this table — they are not here because pairing each with its own falsifier is real,
separate work this PR does not do blind; adding a row without one is exactly the trap this
docstring names. Extend ``REGIONAL_CHILDREN`` and ``[falsifiers]`` together, never one alone.
"""

from __future__ import annotations

from typing import Final, NamedTuple

#: The parent: one per (account, region). Not ``AwsRegion`` — that node is the region *as AWS
#: defines it*, shared by every account; hanging containment off it would make one account's
#: complete listing a candidate-generator for every other account's resources.
PARENT_ENTITY_TYPE: Final = "aws_core__aws_account_region"


class RegionalChild(NamedTuple):
    """A child type an account-region footprint contains."""

    entity_type: str
    #: The parent -> child containment edge slug (``edges/<slug minus __aws_core>.edge.json``).
    edge_type: str
    #: The completeness surface's ``relation``: the listing, in AWS's own terms.
    relation: str
    #: Human noun for the edge description, e.g. "a VPC".
    noun: str
    #: The AWS read that enumerates this type in one region.
    listing: str


REGIONAL_CHILDREN: Final[tuple[RegionalChild, ...]] = (
    RegionalChild("aws_core__aws_vpc", "HOSTS_VPC__aws_core", "account_region.vpcs", "a VPC", "ec2:DescribeVpcs"),
    RegionalChild(
        "aws_core__aws_subnet", "HOSTS_SUBNET__aws_core", "account_region.subnets", "a subnet", "ec2:DescribeSubnets"
    ),
    RegionalChild(
        "aws_core__aws_ec2_instance",
        "HOSTS_EC2_INSTANCE__aws_core",
        "account_region.instances",
        "an EC2 instance",
        "ec2:DescribeInstances",
    ),
    RegionalChild(
        "aws_core__aws_security_group",
        "HOSTS_SECURITY_GROUP__aws_core",
        "account_region.security_groups",
        "a security group",
        "ec2:DescribeSecurityGroups",
    ),
)

CHILD_BY_TYPE: Final = {c.entity_type: c for c in REGIONAL_CHILDREN}

#: Three of the four ``REGIONAL_CHILDREN`` above have NO ``[falsifiers]`` row on THIS branch, which
#: means ``validate_plugin --level loads --strict`` is red on this branch alone today —
#: ``VpcFalsifier`` / ``Ec2InstanceFalsifier`` / ``SecurityGroupFalsifier`` are built and registered
#: on the sibling PR tap-plugin-aws-core#44 ("compute + network falsifier coverage"), not on this
#: PR's base (#46). Only ``SubnetFalsifier`` (also from #46) is live here. This is a deliberate,
#: DOCUMENTED cross-PR dependency, the same shape as this branch's own relationship to #46 (base,
#: retarget after merge): the gate goes green the moment #44 merges into this PR's ancestry, with no
#: further change needed on this side — see the module docstring's "Why only four rows" note and
#: ``tap_plugin.aws_core.falsifiers`` module docstring for how the two pieces fit together. Do not
#: register a competing falsifier for any of these three here; #44 already owns that.
PENDING_FALSIFIER_PR: Final[dict[str, str]] = {
    "aws_core__aws_vpc": "tap-plugin-aws-core#44 (VpcFalsifier)",
    "aws_core__aws_ec2_instance": "tap-plugin-aws-core#44 (Ec2InstanceFalsifier)",
    "aws_core__aws_security_group": "tap-plugin-aws-core#44 (SecurityGroupFalsifier)",
}

#: Region-scoped types that belong in REGIONAL_CHILDREN and are deliberately NOT here yet — see
#: the module docstring. Each needs its own falsifier before it can be added; this tuple is the
#: worklist so the gap is named, not merely absent. (entity_type, the AWS read that would list it)
NOT_YET_WIRED: Final[tuple[tuple[str, str], ...]] = (
    ("aws_core__aws_route_table", "ec2:DescribeRouteTables"),
    ("aws_core__aws_internet_gateway", "ec2:DescribeInternetGateways"),
    ("aws_core__aws_nat_gateway", "ec2:DescribeNatGateways"),
    ("aws_core__aws_network_acl", "ec2:DescribeNetworkAcls"),
    ("aws_core__aws_elastic_ip", "ec2:DescribeAddresses"),
    ("aws_core__aws_vpc_endpoint", "ec2:DescribeVpcEndpoints"),
    ("aws_core__aws_ebs_volume", "ec2:DescribeVolumes"),
    ("aws_core__aws_rds_instance", "rds:DescribeDBInstances"),
)
