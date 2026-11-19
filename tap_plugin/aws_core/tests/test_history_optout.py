"""Published-version types keep no grid history (req-aws-core-models-3; aws-build Q86a-c).

AWS never changes a published version, so a history table for one only ever records re-observation.
Exactly the types below opt out with ``TRACK_HISTORY = False`` (tap req-grid-history-optout); every
other aws_core type, including "version" types that carry a field AWS can change, keeps history.
"""

from __future__ import annotations

import pytest
from django.apps import apps

from tap_grid.history import history_agreement_problems, is_history_enabled

#: The published-version types, each checked against its AWS listing shape (aws-build Q86b).
NO_HISTORY = frozenset(
    {
        "BedrockFlowVersion",
        "ConnectContactFlowModuleVersion",
        "ConnectContactFlowVersion",
        "GreengrassConnectorDefinitionVersion",
        "GreengrassCoreDefinitionVersion",
        "GreengrassDeviceDefinitionVersion",
        "GreengrassFunctionDefinitionVersion",
        "GreengrassGroupVersion",
        "GreengrassLoggerDefinitionVersion",
        "GreengrassResourceDefinitionVersion",
        "GreengrassSubscriptionDefinitionVersion",
        "LambdaLayerVersion",
        "StepfunctionsStateMachineVersion",
    }
)


def _aws_models():
    return [
        m
        for m in apps.get_app_config("aws_core").get_models()
        if getattr(m, "ENTITY_TYPE", "").startswith("aws_core__") and not m.__name__.startswith("Historical")
    ]


def test_exactly_the_published_version_types_opt_out() -> None:
    """Q86b/c: the opt-out set is the published-version list, no more and no fewer."""
    declared = {m.__name__ for m in _aws_models() if m.__dict__.get("TRACK_HISTORY") is False}
    assert declared == NO_HISTORY


def test_an_opted_out_type_has_no_history_model_and_every_other_type_keeps_one() -> None:
    """req-grid-history-optout-2: no Historical<Type> model for an opted-out type; the rest keep theirs."""
    names = {m.__name__ for m in apps.get_app_config("aws_core").get_models()}
    for model in _aws_models():
        tracked = model.__name__ not in NO_HISTORY
        assert is_history_enabled(model) is tracked, model.__name__
        assert (f"Historical{model.__name__}" in names) is tracked, model.__name__


@pytest.mark.django_db
def test_class_row_and_history_model_agree_for_every_aws_core_type() -> None:
    """req-grid-history-optout-9: the class flag, EntityType.track_history and the history model agree."""
    problems = [p for p in history_agreement_problems() if p.entity_type.startswith("aws_core__")]
    assert problems == []
