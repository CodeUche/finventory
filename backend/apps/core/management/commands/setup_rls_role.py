"""
Management command: setup_rls_role

Creates (or updates) the limited-privilege `audity_app` database role that
the Django application should use in production so that Row Level Security
policies are actually enforced at the database level.

Usage
-----
    python manage.py setup_rls_role [--password SECRET]

What it does
------------
1. Creates role `audity_app` (LOGIN, no superuser, no CREATEDB, no CREATEROLE).
2. Grants CONNECT on the current database.
3. Grants USAGE on the `public` schema.
4. Grants SELECT, INSERT, UPDATE, DELETE on all existing tables (and future
   tables via ALTER DEFAULT PRIVILEGES).
5. Grants USAGE / SELECT on all sequences (for auto-increment PKs).
6. Does NOT grant BYPASSRLS — RLS is therefore enforced for this role.

After running this command
--------------------------
Set APP_DATABASE_URL in your environment to a connection string that uses the
`audity_app` credentials (same host/db, different user/password), then in
settings/production.py add:

    import environ
    env = environ.Env()
    if env('APP_DATABASE_URL', default=None):
        DATABASES['default'] = env.db('APP_DATABASE_URL')

Keep DATABASE_URL (superuser) only for the Procfile release step:
    release: python manage.py migrate --noinput

This way migrations run as the table owner (bypasses RLS) and all HTTP
requests run as `audity_app` (RLS enforced).
"""

import secrets

from django.core.management.base import BaseCommand
from django.db import connection
from psycopg2 import sql as pgsql


class Command(BaseCommand):
    help = "Create the limited-privilege audity_app Postgres role for RLS enforcement."

    def add_arguments(self, parser):
        parser.add_argument(
            "--password",
            default=None,
            help="Password for the audity_app role. Auto-generated if omitted.",
        )
        parser.add_argument(
            "--role",
            default="audity_app",
            help="Name of the role to create (default: audity_app).",
        )

    def handle(self, *args, **options):
        role = options["role"]
        password = options["password"] or secrets.token_urlsafe(32)

        with connection.cursor() as cursor:
            # 1. Create role if it doesn't exist
            cursor.execute(
                "SELECT 1 FROM pg_roles WHERE rolname = %s", [role]
            )
            exists = cursor.fetchone()

            R = pgsql.Identifier(role)

            if exists:
                self.stdout.write(f"Role '{role}' already exists — updating password.")
                cursor.execute(
                    pgsql.SQL('ALTER ROLE {} WITH LOGIN PASSWORD %s').format(R),
                    [password],
                )
            else:
                self.stdout.write(f"Creating role '{role}'...")
                cursor.execute(
                    pgsql.SQL(
                        'CREATE ROLE {} WITH LOGIN PASSWORD %s '
                        'NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION'
                    ).format(R),
                    [password],
                )

            # 2. Grant CONNECT on the current database
            db_name = connection.settings_dict["NAME"]
            cursor.execute(
                pgsql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(
                    pgsql.Identifier(db_name), R
                )
            )

            # 3. Grant USAGE on public schema
            cursor.execute(pgsql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(R))

            # 4. Grant DML on all existing tables
            cursor.execute(
                pgsql.SQL(
                    'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}'
                ).format(R)
            )

            # 5. Grant sequence usage (needed for INSERT with serial / uuid default)
            cursor.execute(
                pgsql.SQL(
                    'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}'
                ).format(R)
            )

            # 6. Default privileges for future tables created by migrations
            current_user = connection.settings_dict["USER"]
            CU = pgsql.Identifier(current_user)
            cursor.execute(
                pgsql.SQL(
                    'ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public '
                    'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}'
                ).format(CU, R)
            )
            cursor.execute(
                pgsql.SQL(
                    'ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public '
                    'GRANT USAGE, SELECT ON SEQUENCES TO {}'
                ).format(CU, R)
            )

        self.stdout.write(self.style.SUCCESS(f"\n✓ Role '{role}' is ready.\n"))
        self.stdout.write("  Next steps:")
        self.stdout.write(f"  1. Save this password somewhere safe: {password}")
        self.stdout.write(
            f"  2. Set APP_DATABASE_URL=postgres://{role}:{password}"
            f"@<host>/<db> in your Railway environment."
        )
        self.stdout.write(
            "  3. In settings/production.py add:\n"
            "         if env('APP_DATABASE_URL', default=None):\n"
            "             DATABASES['default'] = env.db('APP_DATABASE_URL')\n"
        )
        self.stdout.write(
            "  4. Keep DATABASE_URL (superuser) only in your Procfile release step:\n"
            "         release: python manage.py migrate --noinput\n"
        )
        self.stdout.write(
            "  Once the app connects as audity_app, RLS policies are fully enforced\n"
            "  and no HTTP request can ever read another tenant's rows — even if\n"
            "  application code has a bug.\n"
        )
