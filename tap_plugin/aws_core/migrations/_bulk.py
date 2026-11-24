"""Migration operations that create many models, or add, remove or alter many fields, without re-rendering the
state for each.

Applying a run of ``CreateModel`` operations one by one re-renders the model state after every one
of them (Django reloads the model and every model related to it, and every history model here has a
foreign key to the user model, which relates them all), so a migration that creates a few hundred
models costs a few hundred full renders: minutes of CPU, growing with every batch added. This
operation adds the whole run to the state first and renders once, then creates the tables. The state
and the SQL are the same as the plain operations' (``tests/test_migrations_bulk.py``).
"""

from __future__ import annotations

from typing import Any

from django.db.migrations.operations.base import Operation
from django.db.migrations.operations.fields import AddField, AlterField, RemoveField
from django.db.models.fields import NOT_PROVIDED
from django.db.migrations.operations.models import CreateModel


class BulkCreateModels(Operation):
    """Create several models in one step; ``operations`` are plain ``CreateModel`` operations."""

    reduces_to_sql = True
    reversible = True
    serialization_expand_args = ["operations"]

    def __init__(self, operations: list[CreateModel]) -> None:
        for op in operations:
            if not isinstance(op, CreateModel):
                raise TypeError(f"BulkCreateModels takes CreateModel operations, got {type(op).__name__}")
        self.operations = list(operations)

    def deconstruct(self):
        return (self.__class__.__qualname__, [self.operations], {})

    def state_forwards(self, app_label, state):
        # With no rendered apps, add_model does not reload each model as it goes; the next access to
        # ``state.apps`` renders every model once.
        state.__dict__.pop("apps", None)
        for op in self.operations:
            op.state_forwards(app_label, state)

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        for op in self.operations:
            model = to_state.apps.get_model(app_label, op.name)
            if self.allow_migrate_model(schema_editor.connection.alias, model):
                schema_editor.create_model(model)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        for op in reversed(self.operations):
            model = from_state.apps.get_model(app_label, op.name)
            if self.allow_migrate_model(schema_editor.connection.alias, model):
                schema_editor.delete_model(model)

    def references_model(self, name, app_label):
        return any(op.references_model(name, app_label) for op in self.operations)

    def describe(self):
        return f"Create {len(self.operations)} models"

    @property
    def migration_name_fragment(self):
        return "bulk_create_models"


class BulkAlterFields(Operation):
    """Alter many fields in one step; ``operations`` are plain ``AlterField`` operations.

    The same cost as :class:`BulkCreateModels`: ``AlterField`` run one at a time renders the whole model state
    again for each field, and this app has hundreds of models and a history model for each. This operation sets
    every field in the state first and renders once on each side, then alters the columns. The state and the SQL
    are the same as the plain operations'.
    """

    reduces_to_sql = True
    reversible = True
    serialization_expand_args = ["operations"]

    def __init__(self, operations: list[AlterField]) -> None:
        for op in operations:
            if not isinstance(op, AlterField):
                raise TypeError(f"BulkAlterFields takes AlterField operations, got {type(op).__name__}")
        self.operations = list(operations)

    def deconstruct(self):
        return (self.__class__.__qualname__, [self.operations], {})

    def state_forwards(self, app_label, state):
        state.__dict__.pop("apps", None)
        for op in self.operations:
            state.models[app_label, op.model_name_lower].fields[op.name] = op.field.clone()

    def _alter(self, app_label, schema_editor, from_state, to_state, operations):
        for op in operations:
            from_model = from_state.apps.get_model(app_label, op.model_name)
            if not self.allow_migrate_model(schema_editor.connection.alias, from_model):
                continue
            to_model = to_state.apps.get_model(app_label, op.model_name)
            schema_editor.alter_field(from_model, from_model._meta.get_field(op.name), to_model._meta.get_field(op.name))

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        self._alter(app_label, schema_editor, from_state, to_state, self.operations)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        self._alter(app_label, schema_editor, from_state, to_state, list(reversed(self.operations)))

    def references_model(self, name, app_label):
        return any(op.references_model(name, app_label) for op in self.operations)

    def describe(self):
        return f"Alter {len(self.operations)} fields"

    @property
    def migration_name_fragment(self):
        return "bulk_alter_fields"


def _plain_fields_only(operations: list[Any], kind: type, name: str) -> list[Any]:
    """``operations`` when every one is a ``kind`` on a non-relational field, else ``TypeError``.

    A relational field changes the state's relation map as well as one model's fields, which the plain operation
    keeps through ``ProjectState``'s own add and remove; these bulk operations set the fields directly, so they
    take only fields that relate to nothing.
    """
    for op in operations:
        if not isinstance(op, kind):
            raise TypeError(f"{name} takes {kind.__name__} operations, got {type(op).__name__}")
        field = getattr(op, "field", None)
        if field is not None and field.is_relation:
            raise TypeError(f"{name} takes non-relational fields only; {op.model_name}.{op.name} is relational")
    return list(operations)


class BulkAddFields(Operation):
    """Add many non-relational fields in one step; ``operations`` are plain ``AddField`` operations.

    The cost :class:`BulkAlterFields` avoids: ``AddField`` run one at a time renders the whole model state again for
    each field, about five seconds a field over this app's models and their history models, so core's spine copies
    (two fields on each of some 1,850 tables, unified-systems-com/tap PR 1352) would take hours to apply. This adds
    every field to the state first and renders once on each side, then adds the columns. The state and the SQL are
    the same as the plain operations' (``tests/test_migrations_bulk.py``).
    """

    reduces_to_sql = True
    reversible = True
    serialization_expand_args = ["operations"]

    def __init__(self, operations: list[AddField]) -> None:
        self.operations = _plain_fields_only(operations, AddField, "BulkAddFields")

    def deconstruct(self):
        return (self.__class__.__qualname__, [self.operations], {})

    def state_forwards(self, app_label, state):
        state.__dict__.pop("apps", None)
        for op in self.operations:
            field = op.field
            if not op.preserve_default:
                field = field.clone()
                field.default = NOT_PROVIDED
            state.models[app_label, op.model_name_lower].fields[op.name] = field

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        for op in self.operations:
            to_model = to_state.apps.get_model(app_label, op.model_name)
            if not self.allow_migrate_model(schema_editor.connection.alias, to_model):
                continue
            from_model = from_state.apps.get_model(app_label, op.model_name)
            field = to_model._meta.get_field(op.name)
            if not op.preserve_default:
                field.default = op.field.default
            schema_editor.add_field(from_model, field)
            if not op.preserve_default:
                field.default = NOT_PROVIDED

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        for op in reversed(self.operations):
            from_model = from_state.apps.get_model(app_label, op.model_name)
            if self.allow_migrate_model(schema_editor.connection.alias, from_model):
                schema_editor.remove_field(from_model, from_model._meta.get_field(op.name))

    def references_model(self, name, app_label):
        return any(op.references_model(name, app_label) for op in self.operations)

    def describe(self):
        return f"Add {len(self.operations)} fields"

    @property
    def migration_name_fragment(self):
        return "bulk_add_fields"


class BulkRemoveFields(Operation):
    """Remove many non-relational fields in one step; ``operations`` are plain ``RemoveField`` operations.

    The same cost and the same remedy as :class:`BulkAddFields` (core's typed ``batch_id``, removed from every
    table, unified-systems-com/tap PR 1352). The state and the SQL are the same as the plain operations'.
    """

    reduces_to_sql = True
    reversible = True
    serialization_expand_args = ["operations"]

    def __init__(self, operations: list[RemoveField]) -> None:
        self.operations = _plain_fields_only(operations, RemoveField, "BulkRemoveFields")

    def deconstruct(self):
        return (self.__class__.__qualname__, [self.operations], {})

    def state_forwards(self, app_label, state):
        # Refuse a relational field here, where the field is first known (RemoveField names no field).
        for op in self.operations:
            if state.models[app_label, op.model_name_lower].fields[op.name].is_relation:
                raise TypeError(f"BulkRemoveFields takes non-relational fields only; {op.model_name}.{op.name} is relational")
        state.__dict__.pop("apps", None)
        for op in self.operations:
            del state.models[app_label, op.model_name_lower].fields[op.name]

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        for op in self.operations:
            from_model = from_state.apps.get_model(app_label, op.model_name)
            if self.allow_migrate_model(schema_editor.connection.alias, from_model):
                schema_editor.remove_field(from_model, from_model._meta.get_field(op.name))

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        for op in reversed(self.operations):
            to_model = to_state.apps.get_model(app_label, op.model_name)
            if not self.allow_migrate_model(schema_editor.connection.alias, to_model):
                continue
            from_model = from_state.apps.get_model(app_label, op.model_name)
            schema_editor.add_field(from_model, to_model._meta.get_field(op.name))

    def references_model(self, name, app_label):
        return any(op.references_model(name, app_label) for op in self.operations)

    def describe(self):
        return f"Remove {len(self.operations)} fields"

    @property
    def migration_name_fragment(self):
        return "bulk_remove_fields"
