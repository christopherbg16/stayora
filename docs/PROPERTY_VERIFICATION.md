# Staya Property Verification

## What is checked

Only the existing client and property-owner roles are used. There is no reviewer/admin-of-the-site role or manual moderation queue. Staya makes the listing decision automatically when an owner submits or edits a property.

Uploaded property photos are decoded and validated as JPG, PNG, or WEBP, limited to 8 MB each and 10 images, stripped of original metadata, and normalized to JPEG. With the owner's consent, Gemini checks listing text and photos for likely abusive, explicit, violent, privacy-sensitive, or unrelated content. Google Places checks the property name and street/city/country address. Staya approves only when the content check is clear and the place/address match; a content flag is rejected, and missing keys or uncertain matches require the owner to correct the listing and resubmit.

A successful Places match is not proof of ownership and does not prove where a photo was taken. Gemini can flag suspicious or unrelated images, but image authenticity is not guaranteed. Do not copy Google Maps photos into listings.

## Supabase setup

Before deploying this code, run `stayora/03_property_review_migration.sql` in the Supabase SQL Editor. It preserves existing listings as approved and sets new submissions to pending until Staya completes the automatic checks. For a new database, the setup scripts include the new columns; keep the migration available for upgrades.

## API keys and privacy

Set a newly rotated `GEMINI_API_KEY` and a Google Places API key with Places API (New) enabled and billing configured. Restrict the Google key to the Places API and allowed server IPs where feasible. Never commit either key. The owner must consent before listing text/photos go to Gemini and listing name/address go to Places; disclose these transfers in the site's privacy notice before production use.

If the owner does not consent, a key is missing, a provider errors, or the address does not match confidently, the listing is set to `action_required` and stays hidden from public queries. Flagged content is set to `rejected`; the owner can edit and resubmit. Only `approved` properties are public.
