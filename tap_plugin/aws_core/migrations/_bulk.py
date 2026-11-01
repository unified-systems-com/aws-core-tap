"""One migration operation that creates many models without re-rendering the state for each.

Applying a run of ``CreateModel`` operations one by one re-renders the model state after every one
of them (Django reloads the model and every model related to it, and every history model here has a
foreign key to the user model, which relates them all), so a migration that creates a few hundred
models costs a few hundred full renders: minutes of CPU, growing with every batch added. This
operation adds the whole run to the state first and renders once, then creates the tables. The state
and the SQL are the same as the plain operations' (``tests/test_migrations_bulk.py``).
"""

from __future__ import annotations

from django.db.migrations.operations.base import Operation
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
