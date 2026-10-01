"""AWS Organizations policy-type vocabulary, shared by the models and the Organizations reader.

No Django imports: the collector and the falsifiers import this without loading the model registry.

Spec: specs/spec-aws-core-v0.md (req-aws-core-organizations-completeness-2, -5, -7, -11, -12)
"""

from __future__ import annotations

#: ``organizations`` ``PolicyType`` enum, read from the pinned botocore (1.43.106) service model.
#: A type AWS adds later is not in this tuple; the reader then refuses to call its listing complete
#: (``organizations.py``) rather than list it into a model that would refuse its ``policy_type``.
POLICY_TYPES: tuple[str, ...] = (
    "SERVICE_CONTROL_POLICY",
    "RESOURCE_CONTROL_POLICY",
    "TAG_POLICY",
    "BACKUP_POLICY",
    "AISERVICES_OPT_OUT_POLICY",
    "CHATBOT_POLICY",
    "DECLARATIVE_POLICY_EC2",
    "SECURITYHUB_POLICY",
    "INSPECTOR_POLICY",
    "UPGRADE_ROLLOUT_POLICY",
    "BEDROCK_POLICY",
    "S3_POLICY",
    "NETWORK_SECURITY_DIRECTOR_POLICY",
    "GUARDDUTY_POLICY",
)

SERVICE_CONTROL_POLICY = "SERVICE_CONTROL_POLICY"
RESOURCE_CONTROL_POLICY = "RESOURCE_CONTROL_POLICY"
TAG_POLICY = "TAG_POLICY"

#: Every type except SCP: SCPs keep their own model (``AwsServiceControlPolicy``), so the generic
#: policy model never holds one and there is never a second SCP node.
OTHER_POLICY_TYPES: tuple[str, ...] = tuple(t for t in POLICY_TYPES if t != SERVICE_CONTROL_POLICY)

#: Authorization policies: documents of IAM-grammar statements (req-aws-core-organizations-completeness-7).
STATEMENT_POLICY_TYPES: frozenset[str] = frozenset({SERVICE_CONTROL_POLICY, RESOURCE_CONTROL_POLICY})
#: Tag policies: one rule per tag key (req-aws-core-organizations-completeness-11).
TAG_RULE_POLICY_TYPES: frozenset[str] = frozenset({TAG_POLICY})
