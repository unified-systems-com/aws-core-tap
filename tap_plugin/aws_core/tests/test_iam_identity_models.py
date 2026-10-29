"""The IAM identity models: group, instance profile, SAML provider, server certificate, virtual MFA device.

They are modelled ahead of their collector entries (req-aws-core-ledger-tranches, tranche 1), so what is pinned
here is the shape of the model itself: the canonical ``tags`` and ``configuration`` fields every node payload
carries, an ARN-or-serial natural key, and the absence of any *typed* field that could hold a credential.

``configuration`` is an open JSON object on every collected model, these included, so the schema cannot keep a
credential out of it. What does is the collector entry's ``persist_configuration`` flag and its sensitivity
review (``add-aws-type``, step 1), which arrive with the manifest entries. For the virtual MFA device
(``Base32StringSeed`` and ``QRCodePNG`` are botocore-sensitive) the flag will be off.
"""

from __future__ import annotations

import pytest
from tap_plugin.aws_core.models.iam_group import IamGroup
from tap_plugin.aws_core.models.iam_instance_profile import IamInstanceProfile
from tap_plugin.aws_core.models.iam_saml_provider import IamSamlProvider
from tap_plugin.aws_core.models.iam_server_certificate import IamServerCertificate
from tap_plugin.aws_core.models.iam_virtual_mfa_device import IamVirtualMfaDevice

MODELS = [IamGroup, IamInstanceProfile, IamSamlProvider, IamServerCertificate, IamVirtualMfaDevice]
KEYS = {
    IamGroup: "group_arn",
    IamInstanceProfile: "instance_profile_arn",
    IamSamlProvider: "provider_arn",
    IamServerCertificate: "certificate_arn",
    IamVirtualMfaDevice: "serial_number",
}
# Names AWS gives the values that enrol or prove a credential; none may ever be a typed model field.
CREDENTIAL_WORDS = ("seed", "qrcode", "qr_code", "private_key", "certificate_body", "certificate_chain", "secret", "password", "credential", "pem", "key_material", "otp")


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
class TestIamIdentityModels:
    def test_the_canonical_fields_are_declared_in_both_schemas(self, model):
        for field in ("tags", "configuration"):
            assert model._meta.get_field(field).default is dict
            assert field in model.FIELD_CRUD_SCHEMA and field in model.FIELD_VALIDATION_SCHEMA

    def test_every_model_field_is_in_both_schemas(self, model):
        declared = {f.name for f in model._meta.get_fields() if f.concrete and not f.primary_key and f.name in model.FIELD_CRUD_SCHEMA}
        assert declared == set(model.FIELD_CRUD_SCHEMA) == set(model.FIELD_VALIDATION_SCHEMA)

    def test_the_natural_key_is_the_arn_or_serial(self, model):
        assert model.NATURAL_KEY == (KEYS[model],)
        assert KEYS[model] in model.FIELD_CRUD_SCHEMA

    def test_no_typed_field_is_named_for_a_credential(self, model):
        names = {f.name for f in model._meta.get_fields()}
        assert not [n for n in names if any(word in n for word in CREDENTIAL_WORDS)]

    def test_the_entity_type_is_the_table(self, model):
        assert model.ENTITY_TYPE == model._meta.db_table
