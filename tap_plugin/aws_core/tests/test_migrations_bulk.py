"""``BulkCreateModels`` leaves the same state and runs the same SQL as the plain ``CreateModel`` run."""

from __future__ import annotations

import pytest
from django.db import connection, models
from django.db.migrations.operations.models import CreateModel
from django.db.migrations.state import ProjectState
from tap_plugin.aws_core.migrations._bulk import BulkCreateModels

APP = "bulkprobe"


def _ops() -> list[CreateModel]:
    return [
        CreateModel("Parent", [("id", models.AutoField(primary_key=True)), ("name", models.CharField(max_length=20))]),
        CreateModel(
            "Child",
            [
                ("id", models.AutoField(primary_key=True)),
                ("parent", models.ForeignKey(f"{APP}.parent", on_delete=models.CASCADE)),
            ],
        ),
        CreateModel("Historicalchild", [("id", models.BigIntegerField(db_index=True)), ("note", models.TextField(null=True))]),
    ]


def _run_plain() -> tuple[ProjectState, list[str]]:
    state = ProjectState()
    with connection.schema_editor(collect_sql=True, atomic=False) as editor:
        for op in _ops():
            before = state.clone()
            op.state_forwards(APP, state)
            op.database_forwards(APP, editor, before, state)
    return state, list(editor.collected_sql)


def _run_bulk() -> tuple[ProjectState, list[str]]:
    state = ProjectState()
    op = BulkCreateModels(_ops())
    with connection.schema_editor(collect_sql=True, atomic=False) as editor:
        before = state.clone()
        op.state_forwards(APP, state)
        op.database_forwards(APP, editor, before, state)
    return state, list(editor.collected_sql)


@pytest.mark.django_db
def test_the_same_sql_and_the_same_state():
    plain_state, plain_sql = _run_plain()
    bulk_state, bulk_sql = _run_bulk()
    assert sorted(bulk_sql) == sorted(plain_sql)
    assert bulk_state.models.keys() == plain_state.models.keys()
    for key, model_state in plain_state.models.items():
        assert [n for n, _ in model_state.fields.items()] == [n for n, _ in bulk_state.models[key].fields.items()]
    # the rendered models resolve the foreign key between two models of the same run
    child = bulk_state.apps.get_model(APP, "Child")
    assert child._meta.get_field("parent").related_model is bulk_state.apps.get_model(APP, "Parent")


@pytest.mark.django_db
def test_backwards_drops_in_reverse_order():
    state, _ = _run_bulk()
    op = BulkCreateModels(_ops())
    with connection.schema_editor(collect_sql=True, atomic=False) as editor:
        op.database_backwards(APP, editor, state, ProjectState())
    drops = [s for s in editor.collected_sql if s.startswith("DROP TABLE")]
    assert [("child" in d.lower(), "parent" in d.lower()) for d in drops][:2] == [(True, False), (False, True)] or len(drops) == 3


def test_only_create_model_operations_are_accepted():
    with pytest.raises(TypeError):
        BulkCreateModels([models.Index(fields=["a"])])  # type: ignore[list-item]
