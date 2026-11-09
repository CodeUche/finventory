"""Unit tests for apps.core.rls_policy._run's failure handling.

_run used to log a warning and move on when ALTER TABLE ... ENABLE ROW LEVEL
SECURITY failed for a table, so a migration could complete "successfully"
while leaving a table with no tenant isolation at all, with nothing but a line
in a log nobody reads. It now raises once every table has had its best-effort
attempt, so a failed migration is a failed migration.

These mock schema_editor/cursor rather than needing a real Postgres connection,
so they run under the default (SQLite) test settings too, not just the
Postgres-only lane.
"""

from unittest.mock import MagicMock

from django.test import SimpleTestCase

from apps.core.rls_policy import _run, enable_sql


def _pg_schema_editor(failing_tables=()):
    """A schema_editor double: vendor is postgresql, and cursor.execute raises
    for any table in `failing_tables`, keyed by substring match on the SQL."""
    editor = MagicMock()
    editor.connection.vendor = "postgresql"
    cursor = MagicMock()

    def _execute(sql):
        for table in failing_tables:
            if f"ALTER TABLE {table} " in sql:
                raise Exception(f"permission denied for table {table}")

    cursor.execute.side_effect = _execute
    editor.connection.cursor.return_value.__enter__.return_value = cursor
    return editor, cursor


class RunRaisesOnFailureTests(SimpleTestCase):
    databases = {"default"}

    def test_all_tables_succeed_raises_nothing(self):
        editor, cursor = _pg_schema_editor()
        _run(editor, ["a", "b", "c"], enable_sql, "test-label")
        self.assertEqual(cursor.execute.call_count, 3)

    def test_one_failing_table_raises(self):
        editor, cursor = _pg_schema_editor(failing_tables=["b"])
        with self.assertRaises(RuntimeError) as ctx:
            _run(editor, ["a", "b", "c"], enable_sql, "test-label")
        self.assertIn("b", str(ctx.exception))
        self.assertIn("test-label", str(ctx.exception))

    def test_one_failing_table_does_not_stop_the_others(self):
        """Per-table isolation is preserved: a failure on table b must not
        prevent a and c from still getting their best-effort attempt."""
        editor, cursor = _pg_schema_editor(failing_tables=["b"])
        with self.assertRaises(RuntimeError):
            _run(editor, ["a", "b", "c"], enable_sql, "test-label")
        self.assertEqual(cursor.execute.call_count, 3)

    def test_every_failing_table_is_named_in_the_error(self):
        editor, cursor = _pg_schema_editor(failing_tables=["a", "c"])
        with self.assertRaises(RuntimeError) as ctx:
            _run(editor, ["a", "b", "c"], enable_sql, "test-label")
        self.assertIn("a", str(ctx.exception))
        self.assertIn("c", str(ctx.exception))
        self.assertIn("2 table(s)", str(ctx.exception))

    def test_sqlite_is_a_silent_no_op(self):
        editor = MagicMock()
        editor.connection.vendor = "sqlite"
        _run(editor, ["a", "b"], enable_sql, "test-label")
        editor.connection.cursor.assert_not_called()
