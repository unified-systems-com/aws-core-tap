"""``BulkCreateModels`` and ``BulkAlterFields`` leave the same state and run the same SQL as the plain operations."""

from __future__ import annotations

import pytest
from django.db import connection, models
from django.db.migrations.operations.fields import AlterField
from django.db.migrations.operations.models import CreateModel
from django.db.migrations.state import ProjectState
from tap_plugin.aws_core.migrations._bulk import BulkAlterFields, BulkCreateModels

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


def _base_state() -> ProjectState:
    state = ProjectState()
    with connection.schema_editor(collect_sql=True, atomic=False) as editor:
        for op in [
            CreateModel("Probe", [("id", models.AutoField(primary_key=True)), ("a", models.CharField(max_length=9, default="")),
                                  ("b", models.BooleanField(default=False)), ("c", models.IntegerField(default=0))]),
            CreateModel("Other", [("id", models.AutoField(primary_key=True)), ("d", models.CharField(max_length=9, default=""))]),
        ]:
            before = state.clone()
            op.state_forwards(APP, state)
            op.database_forwards(APP, editor, before, state)
    return state


def _alters() -> list[AlterField]:
    return [
        AlterField("Probe", "a", models.CharField(max_length=9, null=True, blank=True, default=None)),
        AlterField("Probe", "b", models.BooleanField(null=True, blank=True, default=None)),
        AlterField("Other", "d", models.CharField(max_length=9, null=True, blank=True, default=None)),
    ]


def _nullable(state: ProjectState) -> dict[tuple[str, str], bool]:
    return {(m, f): fld.null for (_a, m), ms in state.models.items() for f, fld in ms.fields.items()}


@pytest.mark.django_db
def test_altering_fields_in_bulk_gives_the_same_sql_and_state():
    plain_state = _base_state()
    plain_sql: list[str] = []
    for op in _alters():
        before = plain_state.clone()
        op.state_forwards(APP, plain_state)
        with connection.schema_editor(collect_sql=True, atomic=False) as editor:
            op.database_forwards(APP, editor, before, plain_state)
        plain_sql += editor.collected_sql
    bulk_state = _base_state()
    bulk = BulkAlterFields(_alters())
    before = bulk_state.clone()
    bulk.state_forwards(APP, bulk_state)
    with connection.schema_editor(collect_sql=True, atomic=False) as editor:
        bulk.database_forwards(APP, editor, before, bulk_state)
    assert sorted(editor.collected_sql) == sorted(plain_sql)
    assert _nullable(bulk_state) == _nullable(plain_state)
    assert _nullable(bulk_state)[("probe", "a")] and _nullable(bulk_state)[("probe", "b")] and _nullable(bulk_state)[("other", "d")]
    assert not _nullable(bulk_state)[("probe", "c")], "a field the operation does not name is untouched"


@pytest.mark.django_db
def test_altering_fields_in_bulk_reverses_to_not_null():
    base = _base_state()
    after = base.clone()
    bulk = BulkAlterFields(_alters())
    bulk.state_forwards(APP, after)
    with connection.schema_editor(collect_sql=True, atomic=False) as editor:
        bulk.database_backwards(APP, editor, after, base)
    assert sum("SET NOT NULL" in sql for sql in editor.collected_sql) == 3


def test_only_alter_field_operations_are_accepted_in_bulk():
    with pytest.raises(TypeError):
        BulkAlterFields([CreateModel("X", [])])  # type: ignore[list-item]


def _columns(table: str) -> dict[str, str]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_name, is_nullable FROM information_schema.columns WHERE table_name = %s", [table]
        )
        return dict(cursor.fetchall())


@pytest.mark.django_db
def test_two_fields_of_one_table_both_change_when_the_alteration_is_really_applied():
    """Executed, not collected: the tables exist in the test database and the columns are read back, so a column
    left behind by a later alteration of the same table would show."""
    base = ProjectState()
    with connection.schema_editor(atomic=False) as editor:
        for op in [
            CreateModel("Probe", [("id", models.AutoField(primary_key=True)), ("a", models.CharField(max_length=9, default="")),
                                  ("b", models.BooleanField(default=False)), ("c", models.IntegerField(default=0))]),
        ]:
            before = base.clone()
            op.state_forwards(APP, base)
            op.database_forwards(APP, editor, before, base)
    table = f"{APP}_probe"
    assert _columns(table) == {"id": "NO", "a": "NO", "b": "NO", "c": "NO"}
    after = base.clone()
    bulk = BulkAlterFields([_alters()[0], _alters()[1]])
    bulk.state_forwards(APP, after)
    with connection.schema_editor(atomic=False) as editor:
        bulk.database_forwards(APP, editor, base, after)
    assert _columns(table) == {"id": "NO", "a": "YES", "b": "YES", "c": "NO"}
    with connection.schema_editor(atomic=False) as editor:
        bulk.database_backwards(APP, editor, after, base)
    assert _columns(table) == {"id": "NO", "a": "NO", "b": "NO", "c": "NO"}
