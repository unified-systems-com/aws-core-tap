"""AWS SES Mail Manager Address List — an AWS SES Mail Manager Address List."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class SesMailManagerAddressList(BaseModel):
    """An AWS SES Mail Manager Address List, listed by ListAddressLists. Only its identity, name and tags are collected; the rest of the response has not been reviewed for sensitive values, so none of it is stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_ses_mail_manager_address_list"
    ENTITY_NAME: ClassVar[str] = "AWS SES Mail Manager Address List"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS SES Mail Manager Address List."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The object's ARN (AddressListArn): unique across accounts and regions.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("ses_mail_manager_address_list_arn",)
    ARN_RESOURCE: ClassVar[str | None] = "ses:mailmanager-address-list"

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string"},
        "ses_mail_manager_address_list_arn": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = []

    name = models.CharField(max_length=255, blank=True, default="")
    ses_mail_manager_address_list_arn = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_ses_mail_manager_address_list"

    def get_name(self) -> str:
        return self.name or self.ses_mail_manager_address_list_arn

    def __str__(self) -> str:
        return self.get_name()
