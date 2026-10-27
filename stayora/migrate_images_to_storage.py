import argparse
import base64
import io
import os

from PIL import Image, UnidentifiedImageError
from supabase import create_client

from storage import MAX_IMAGE_BYTES, upload_image
from supabase_client import supabase_url


IMAGE_COLUMNS = {
    'hotels': ('main_image',),
    'hotel_images': ('image_data',),
    'rooms': ('image_data',),
    'users': ('profile_image',),
    'promotions': ('image_data',),
    'trending_destinations': ('image_data',),
}
PAGE_SIZE = 200


def _legacy_image_bytes(value):
    if not value or value.startswith(('https://', 'http://')):
        return None
    encoded = value.split(',', 1)[1] if value.startswith('data:') else value
    raw = base64.b64decode(encoded, validate=True)
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError('Legacy image exceeds the 8 MB limit.')
    try:
        with Image.open(io.BytesIO(raw)) as source:
            source.verify()
        with Image.open(io.BytesIO(raw)) as source:
            converted = source.convert('RGB')
            output = io.BytesIO()
            converted.save(output, format='JPEG', quality=90, optimize=True)
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError('Legacy image is not a supported image.') from exc
    return output.getvalue()


def migrate_images(apply_changes=False):
    service_key = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '').strip()
    if not service_key:
        raise RuntimeError('Set SUPABASE_SERVICE_ROLE_KEY before migrating images.')
    client = create_client(supabase_url, service_key)

    scanned = 0
    migrated = 0
    for table, columns in IMAGE_COLUMNS.items():
        offset = 0
        while True:
            selection = ','.join(('id', *columns))
            rows = client.table(table).select(selection).range(offset, offset + PAGE_SIZE - 1).execute().data or []
            if not rows:
                break
            scanned += len(rows) * len(columns)
            for row in rows:
                for column in columns:
                    value = row.get(column)
                    if not value or value.startswith(('https://', 'http://')):
                        continue
                    raw = _legacy_image_bytes(value)
                    if raw is None:
                        continue
                    migrated += 1
                    if apply_changes:
                        url = upload_image(
                            raw,
                            'image/jpeg',
                            f'legacy/{table}',
                            filename=str(row['id']),
                        )
                        client.table(table).update({column: url}).eq('id', row['id']).execute()
            if len(rows) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
    return scanned, migrated


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Move legacy base64 images to Supabase Storage.')
    parser.add_argument('--apply', action='store_true', help='Upload images and replace database values with URLs.')
    arguments = parser.parse_args()
    scanned_count, migrated_count = migrate_images(apply_changes=arguments.apply)
    mode = 'Applied' if arguments.apply else 'Dry run'
    print(f'{mode}: scanned {scanned_count} image fields; {migrated_count} legacy images found.')