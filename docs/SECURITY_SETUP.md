# Security Setup

## Required Environment

Set a stable `SECRET_KEY` with at least 32 characters in `stayora/.env`. Generate one locally with:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

Set `STRIPE_WEBHOOK_SECRET` from the Stripe webhook endpoint. Configure the endpoint URL as `https://<host>/payments/webhook` and subscribe to `checkout.session.completed` and `checkout.session.async_payment_succeeded`.

Set `SUPABASE_SERVICE_ROLE_KEY` only in the server environment. Never expose it to browser code or commit it. The current public `SUPABASE_KEY` is not sufficient for trusted Storage uploads. `SUPABASE_STORAGE_BUCKET` defaults to `stayora-images`.

## Database And Storage Migration

1. Review and apply `stayora/04_booking_storage_migration.sql` in the Supabase SQL Editor. It aborts if existing reservations overlap, exceed 365 nights, or contain duplicate Stripe session IDs; resolve those rows before retrying.
2. Confirm the `stayora-images` bucket exists and serves public reads. The migration creates the bucket and public read policy; uploads remain server-side through the service role key.
3. From the `stayora` application directory, run `python migrate_images_to_storage.py` for a read-only count. Run `python migrate_images_to_storage.py --apply` to upload legacy base64 images and replace their database values with URLs.
4. Verify listing, room, and profile images before removing any legacy database data.

## Production Rate Limiting

`RATELIMIT_STORAGE_URI=memory://` is for local development only. Configure a shared Redis-compatible URI in production so limits apply across workers and restarts.