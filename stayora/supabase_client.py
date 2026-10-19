import os
from pathlib import Path
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_KEY")
if not supabase_url or not supabase_key:
    raise RuntimeError("Set SUPABASE_URL and SUPABASE_KEY in stayora/.env or the environment.")

supabase: Client = create_client(
    supabase_url,
    supabase_key
)
