BEGIN;

ALTER TABLE hotels ADD COLUMN IF NOT EXISTS review_status TEXT;
ALTER TABLE hotels ADD COLUMN IF NOT EXISTS moderation_status TEXT NOT NULL DEFAULT 'not_checked';
ALTER TABLE hotels ADD COLUMN IF NOT EXISTS moderation_notes TEXT;
ALTER TABLE hotels ADD COLUMN IF NOT EXISTS submitted_at TIMESTAMPTZ DEFAULT NOW();

-- Keep existing listings live; new submissions pass Staya's automated checks.
UPDATE hotels SET review_status = 'approved' WHERE review_status IS NULL;
ALTER TABLE hotels ALTER COLUMN review_status SET DEFAULT 'pending';
ALTER TABLE hotels ALTER COLUMN review_status SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_hotels_review_status ON hotels (review_status, submitted_at);

COMMIT;
