import os
import uuid
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from supabase import create_client

from supabase_client import supabase_url


MAX_IMAGE_BYTES = 8 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/webp'}
_storage_client = None


def _bucket():
    global _storage_client
    service_key = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '').strip()
    if not supabase_url or not service_key:
        raise RuntimeError('Configure SUPABASE_SERVICE_ROLE_KEY for server-side image uploads.')
    if _storage_client is None:
        _storage_client = create_client(supabase_url, service_key)
    bucket_name = os.environ.get('SUPABASE_STORAGE_BUCKET', 'stayora-images')
    return _storage_client.storage.from_(bucket_name)


def upload_image(data, mime_type, folder, filename=None):
    if mime_type not in ALLOWED_IMAGE_TYPES:
        raise ValueError('Unsupported image type.')
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ValueError('Image must be 8 MB or smaller.')
    extension = {'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp'}[mime_type]
    object_name = filename or uuid.uuid4().hex
    path = f'{folder.strip("/")}/{object_name}.{extension}'
    bucket = _bucket()
    bucket.upload(path, data, {'content-type': mime_type, 'upsert': 'true' if filename else 'false'})
    return bucket.get_public_url(path)


def download_public_image(url):
    parsed = urlsplit(url or '')
    expected = urlsplit(supabase_url or '')
    bucket_name = os.environ.get('SUPABASE_STORAGE_BUCKET', 'stayora-images')
    allowed_prefix = f'/storage/v1/object/public/{bucket_name}/'
    if parsed.scheme != 'https' or parsed.hostname != expected.hostname or not parsed.path.startswith(allowed_prefix):
        raise ValueError('Image URL is not in the configured public storage bucket.')
    request = Request(url, headers={'User-Agent': 'Stayora-image-check/1.0'})
    with urlopen(request, timeout=10) as response:
        data = response.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError('Stored image exceeds the size limit.')
    return data