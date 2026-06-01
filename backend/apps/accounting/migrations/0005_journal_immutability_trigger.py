"""
PostgreSQL trigger that enforces JournalEntry immutability at the database level.

This complements the Python-level guard in JournalEntry.save() by blocking
direct SQL updates to core financial fields on posted entries — even from
database tools that bypass the ORM (psql, pgAdmin, DBA scripts).

Protected fields when status='posted':
  - status       (can't un-post an entry)
  - entry_date   (audit trail integrity)
  - reference    (journal reference is permanent)

Fields intentionally NOT protected (allowed post-post updates):
  - gl_post_status / gl_post_error  (GL retry workflow needs to update these)
  - reconciled_at                   (bank reconciliation marks entries later)
  - updated_at                      (auto-managed by Django)

This migration is a no-op on non-PostgreSQL databases (e.g. SQLite used in tests).
"""

from django.db import migrations


class RunSQLIfPostgres(migrations.RunSQL):
    """RunSQL that silently skips execution on non-PostgreSQL databases."""

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor == "postgresql":
            super().database_forwards(app_label, schema_editor, from_state, to_state)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor == "postgresql":
            super().database_backwards(app_label, schema_editor, from_state, to_state)


class Migration(migrations.Migration):

    dependencies = [
        ('accounting', '0004_accountmapping_journalentry_source_ref_and_more'),
    ]

    operations = [
        RunSQLIfPostgres(
            sql="""
            CREATE OR REPLACE FUNCTION prevent_posted_journal_mutation()
            RETURNS TRIGGER AS $$
            BEGIN
                IF OLD.status = 'posted' AND (
                    NEW.status    IS DISTINCT FROM OLD.status    OR
                    NEW.entry_date IS DISTINCT FROM OLD.entry_date OR
                    NEW.reference  IS DISTINCT FROM OLD.reference
                ) THEN
                    RAISE EXCEPTION
                        'Cannot modify immutable fields on posted journal entry (id=%). '
                        'Status, entry_date, and reference are permanent once posted.',
                        OLD.id
                        USING ERRCODE = 'restrict_violation';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            DROP TRIGGER IF EXISTS journal_entry_immutability ON accounting_journalentry;

            CREATE TRIGGER journal_entry_immutability
            BEFORE UPDATE ON accounting_journalentry
            FOR EACH ROW
            EXECUTE FUNCTION prevent_posted_journal_mutation();
            """,
            reverse_sql="""
            DROP TRIGGER IF EXISTS journal_entry_immutability ON accounting_journalentry;
            DROP FUNCTION IF EXISTS prevent_posted_journal_mutation();
            """,
        ),
    ]
