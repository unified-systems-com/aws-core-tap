"""API Gateway HTTP API — an Amazon API Gateway v2 HTTP API."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class ApiGatewayHttpApi(BaseModel):
    """An Amazon API Gateway v2 HTTP API."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_apigateway_http_api"
    ENTITY_NAME: ClassVar[str] = "API Gateway HTTP API"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An Amazon API Gateway v2 HTTP API — a managed HTTP front door whose routes "
        "integrate with backend targets (typically Lambda) and whose authorizers "
        "gate access (typically Cognito JWT)."
    )
    ENTITY_ICON: ClassVar[str] = "aws-apigateway"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The API's ARN, the boto3 collector's identity for it
    # (derived as _api_arn); api_id alone is unique only within a region.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("api_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#DECDFF", "border": "#8C4FFF", "label": "#271647"},
        }
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "api_id": {"type": "string"},
        "api_arn": {"type": "string"},
        "api_endpoint": {"type": "string"},
        "protocol_type": {"type": "string"},
        "route_authorization_types": {"type": ["object", "null"], "additionalProperties": {"type": "string", "minLength": 1}},
        "tags": {"type": ["object", "null"]},
        "configuration": {"type": "object"},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    api_id = models.CharField(max_length=128, blank=True, default="")
    api_arn = models.CharField(max_length=512, blank=True, default="")
    api_endpoint = models.CharField(max_length=512, blank=True, default="")
    protocol_type = models.CharField(max_length=32, blank=True, default="")
    # {RouteKey: AuthorizationType} from GetRoutes: NONE, AWS_IAM, JWT, or
    # CUSTOM (a Lambda authorizer). Null when GetRoutes failed, so a denied
    # listing never reads as "no open routes". A typed field because this type's
    # configuration is not stored (integrations carry credentials), and without
    # it which routes are open would be lost.
    route_authorization_types = models.JSONField(null=True, blank=True, default=None)
    tags = models.JSONField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_apigateway_http_api"

    def get_name(self) -> str:
        return self.name

    def __str__(self) -> str:
        return self.name
