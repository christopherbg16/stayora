BEGIN;

CREATE EXTENSION IF NOT EXISTS btree_gist;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM reservations
    WHERE nights < 1 OR nights > 365
  ) OR EXISTS (
    SELECT 1 FROM property_reservations
    WHERE nights < 1 OR nights > 365
  ) THEN
    RAISE EXCEPTION 'Fix reservations with nights outside 1..365 before applying this migration.';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM reservations a
    JOIN reservations b
      ON a.room_id = b.room_id
     AND a.id < b.id
     AND daterange(a.start_date, a.start_date + a.nights, '[)')
         && daterange(b.start_date, b.start_date + b.nights, '[)')
  ) THEN
    RAISE EXCEPTION 'Resolve overlapping room reservations before applying this migration.';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM property_reservations a
    JOIN property_reservations b
      ON a.property_id = b.property_id
     AND a.id < b.id
     AND daterange(a.start_date, a.start_date + a.nights, '[)')
         && daterange(b.start_date, b.start_date + b.nights, '[)')
  ) THEN
    RAISE EXCEPTION 'Resolve overlapping property reservations before applying this migration.';
  END IF;

  IF EXISTS (
    SELECT 1 FROM reservations
    WHERE payment_id ~ '^cs_'
    GROUP BY payment_id HAVING COUNT(*) > 1
  ) OR EXISTS (
    SELECT 1 FROM property_reservations
    WHERE payment_id ~ '^cs_'
    GROUP BY payment_id HAVING COUNT(*) > 1
  ) THEN
    RAISE EXCEPTION 'Resolve duplicate Stripe session IDs before applying this migration.';
  END IF;
END $$;

ALTER TABLE reservations
  ADD CONSTRAINT reservations_nights_valid CHECK (nights BETWEEN 1 AND 365),
  ADD CONSTRAINT reservations_no_room_date_overlap
    EXCLUDE USING gist (
      room_id WITH =,
      daterange(start_date, start_date + nights, '[)') WITH &&
    );

ALTER TABLE property_reservations
  ADD CONSTRAINT property_reservations_nights_valid CHECK (nights BETWEEN 1 AND 365),
  ADD CONSTRAINT property_reservations_no_date_overlap
    EXCLUDE USING gist (
      property_id WITH =,
      daterange(start_date, start_date + nights, '[)') WITH &&
    );

CREATE UNIQUE INDEX reservations_stripe_payment_id_unique
  ON reservations (payment_id)
  WHERE payment_id ~ '^cs_';

CREATE UNIQUE INDEX property_reservations_stripe_payment_id_unique
  ON property_reservations (payment_id)
  WHERE payment_id ~ '^cs_';

INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
  'stayora-images',
  'stayora-images',
  true,
  8388608,
  ARRAY['image/jpeg', 'image/png', 'image/webp']
)
ON CONFLICT (id) DO UPDATE
SET public = EXCLUDED.public,
    file_size_limit = EXCLUDED.file_size_limit,
    allowed_mime_types = EXCLUDED.allowed_mime_types;

DROP POLICY IF EXISTS "Public read Stayora images" ON storage.objects;
CREATE POLICY "Public read Stayora images"
  ON storage.objects FOR SELECT
  TO anon, authenticated
  USING (bucket_id = 'stayora-images');

COMMIT;