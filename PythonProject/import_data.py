"""
Import data from supabase_import.sql into Supabase using the REST API.
Imports in FK-safe dependency order.
"""
import re
import os
from supabase import create_client

SUPABASE_URL = "https://dyujezlpsehpdwovwstl.supabase.co"
SUPABASE_KEY = "sb_secret_ECqFyFxbmBXUZKoYzzHnsA_1Hw21gQ1"
SQL_FILE = "supabase_import.sql"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

IMPORT_ORDER = [
    "users",
    "hotels",
    "rooms",
    "hotel_images",
    "hotel_reviews",
    "promotions",
    "property_reservations",
    "reservations",
    "activities",
    "trending_destinations",
]


def delete_all_data():
    """Delete all existing data in reverse FK order."""
    print("Deleting existing data...")
    tables_to_clear = [
        "reservations",
        "property_reservations",
        "hotel_reviews",
        "hotel_images",
        "rooms",
        "promotions",
        "activities",
        "trending_destinations",
        "hotels",
        "users",
    ]
    for table in tables_to_clear:
        try:
            supabase.table(table).delete().neq("id", -1).execute()
            print(f"  Cleared {table}")
        except Exception as e:
            print(f"  Error clearing {table}: {e}")


def parse_sql_row(row_text, num_columns):
    """Parse a single SQL row like (1, 'text', NULL) into a list of values,
    properly handling commas inside strings and escaped quotes."""
    row_text = row_text.strip()
    if row_text.startswith('('):
        if row_text.endswith(');') or row_text.endswith('),'):
            row_text = row_text[1:-2]
        elif row_text.endswith(')'):
            row_text = row_text[1:-1]

    values = []
    current = ''
    in_string = False
    i = 0
    while i < len(row_text):
        ch = row_text[i]

        if in_string:
            if ch == '\\' and i + 1 < len(row_text) and row_text[i + 1] == "'":
                current += "'"
                i += 2
                continue
            elif ch == "'":
                in_string = False
                current += ch
            else:
                current += ch
            i += 1
            continue

        if ch == "'":
            in_string = True
            current += ch
            i += 1
            continue

        if ch == ',':
            values.append(current.strip())
            current = ''
            i += 1
            continue

        current += ch
        i += 1

    if current.strip():
        values.append(current.strip())

    return values


def parse_value(val_text):
    val_text = val_text.strip()
    if val_text.upper() == 'NULL':
        return None
    if val_text.startswith("'") and val_text.endswith("'"):
        s = val_text[1:-1]
        s = s.replace("\\'", "'").replace("''", "'")
        return s
    try:
        if '.' in val_text:
            return float(val_text)
        return int(val_text)
    except ValueError:
        return val_text


def extract_insert_blocks(content):
    """Extract all INSERT statements into {table_name: [rows]}."""
    insert_pattern = re.compile(
        r'INSERT INTO "(\w+)"\s*\(([^)]+)\)\s*VALUES\s*(.+?);',
        re.DOTALL
    )
    matches = insert_pattern.findall(content)

    blocks = {}
    for table_name, cols_str, values_block in matches:
        columns = [c.strip().strip('"') for c in cols_str.split(',')]

        rows_raw = []
        depth = 0
        current = ''
        in_str = False

        for ch in values_block:
            if in_str:
                if ch == '\\':
                    current += ch
                    continue
                elif ch == "'":
                    in_str = False
                current += ch
                continue

            if ch == "'":
                in_str = True
                current += ch
                continue

            if ch == '(' and depth == 0 and not current.strip():
                current = '('
                depth = 1
                continue

            if ch == '(':
                current += ch
                depth += 1
                continue

            if ch == ')':
                current += ch
                depth -= 1
                if depth == 0:
                    rows_raw.append((current, columns))
                    current = ''
                continue

            if current:
                current += ch

        if table_name not in blocks:
            blocks[table_name] = []
        blocks[table_name].extend(rows_raw)

    return blocks


def import_table(supabase, table_name, rows, skip_fk_errors=False):
    """Import rows into a table."""
    inserted = 0
    errors = 0
    for row_str, columns in rows:
        try:
            values = parse_sql_row(row_str, len(columns))
            if len(values) != len(columns):
                print(f"  SKIP: expected {len(columns)} vals, got {len(values)}")
                errors += 1
                continue

            record = {}
            for j, col in enumerate(columns):
                record[col] = parse_value(values[j])

            supabase.table(table_name).insert(record).execute()
            inserted += 1

            if inserted % 10 == 0 and (inserted > 10 or errors > 0):
                print(f"  {inserted} rows inserted... (errors: {errors})")

        except Exception as e:
            msg = str(e)
            if skip_fk_errors and 'violates foreign key' in msg:
                print(f"  FK SKIP: {msg[:80]}")
                errors += 1
                continue
            print(f"  ERROR on row: {msg[:120]}")
            errors += 1
            if errors > 5:
                print("  Too many errors, moving on.")
                return inserted

    print(f"  {table_name}: {inserted} rows, {errors} errors")
    return inserted


def fix_schema_via_sql_editor():
    """Print SQL commands the user needs to run in Supabase SQL Editor."""
    print("""
╔══════════════════════════════════════════════════════════════╗
║  FIX NEEDED: Please run these in Supabase SQL Editor first ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  1. ALTER TABLE users ALTER COLUMN password_hash TYPE TEXT;  ║
║                                                              ║
║  (This fixes the 'value too long' error for scrypt hashes   ║
║   that exceed VARCHAR(255).)                                 ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
""")


def main():
    if not os.path.exists(SQL_FILE):
        print(f"Error: {SQL_FILE} not found!")
        return

    fix_schema_via_sql_editor()
    proceed = input("Have you run the ALTER TABLE command above? (y/N): ")
    if proceed.lower() != 'y':
        print("Please run the SQL command first, then re-run this script.")
        return

    with open(SQL_FILE, 'r', encoding='utf-8') as f:
        content = f.read()

    blocks = extract_insert_blocks(content)
    print(f"Found INSERT blocks for: {list(blocks.keys())}")

    delete_all_data()

    print("\nImporting in FK-safe order...")
    total = 0
    for table in IMPORT_ORDER:
        if table not in blocks:
            print(f"\n{table}: no data to import")
            continue
        print(f"\n{table}:")
        count = import_table(supabase, table, blocks[table])
        total += count

    # Import any remaining tables not in IMPORT_ORDER
    remaining = [t for t in blocks if t not in IMPORT_ORDER]
    for table in remaining:
        print(f"\n{table}:")
        count = import_table(supabase, table, blocks[table])
        total += count

    print(f"\nDone! {total} total rows inserted.")


if __name__ == '__main__':
    main()
