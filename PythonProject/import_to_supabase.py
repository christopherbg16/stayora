"""
Import supabase_import.sql directly into Supabase via direct PostgreSQL connection.

Usage:
1. Go to Supabase Dashboard → Project Settings → Database → Connection string
2. Copy the URI (looks like: postgresql://postgres:xxxx@db.xxxx.supabase.co:5432/postgres)
3. Run: pip install psycopg2-binary
4. Run: python import_to_supabase.py "postgresql://postgres:YOUR_PASSWORD@db.xxxx.supabase.co:5432/postgres"
"""

import sys
import re
import os

SQL_FILE = "supabase_import.sql"


def split_sql_statements(sql_text):
    """Split SQL text into individual statements."""
    statements = []
    current = []
    for line in sql_text.split('\n'):
        current.append(line)
        stripped = line.strip()
        if stripped.endswith(';') and not stripped.startswith('--'):
            statements.append('\n'.join(current))
            current = []
    if current:
        statements.append('\n'.join(current))
    return statements


def main():
    if len(sys.argv) < 2:
        print("Error: Missing database connection string.")
        print()
        print("To find your connection string:")
        print("  1. Go to https://supabase.com/dashboard")
        print("  2. Select your project")
        print("  3. Go to Project Settings → Database")
        print("  4. Copy the Connection string (URI format)")
        print()
        print("Usage: python import_to_supabase.py \"postgresql://postgres:password@db.xxx.supabase.co:5432/postgres\"")
        sys.exit(1)

    conn_str = sys.argv[1]

    try:
        import psycopg2
    except ImportError:
        print("Installing psycopg2-binary...")
        os.system("pip install psycopg2-binary")
        import psycopg2

    if not os.path.exists(SQL_FILE):
        print(f"Error: {SQL_FILE} not found!")
        sys.exit(1)

    print(f"Reading {SQL_FILE}...")
    with open(SQL_FILE, 'r', encoding='utf-8') as f:
        sql_text = f.read()

    statements = split_sql_statements(sql_text)
    print(f"Found {len(statements)} SQL statements to execute")

    print("Connecting to database...")
    conn = psycopg2.connect(conn_str)
    conn.autocommit = True
    cur = conn.cursor()

    success = 0
    errors = 0

    for i, stmt in enumerate(statements):
        stmt_stripped = stmt.strip()
        if not stmt_stripped or stmt_stripped.startswith('--'):
            continue

        # Skip comment-only lines
        if all(l.strip().startswith('--') for l in stmt_stripped.split('\n')):
            continue

        try:
            cur.execute(stmt_stripped)
            success += 1
            if i % 10 == 0 or success % 10 == 0:
                print(f"  Executed {success}/{len(statements)}...")
        except Exception as e:
            print(f"  ERROR on statement {i}: {e}")
            print(f"  Statement (first 200 chars): {stmt_stripped[:200]}")
            errors += 1
            if errors > 5:
                print("Too many errors, aborting.")
                break

    cur.close()
    conn.close()

    print(f"\nDone! {success} statements executed successfully, {errors} errors.")


if __name__ == '__main__':
    main()
