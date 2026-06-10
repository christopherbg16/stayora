"""
Run this SQL in your Supabase SQL Editor (https://supabase.com/dashboard)
to create the required tables for the StayOra booking system.

Execute ALL statements below in order.
"""

SETUP_SQL = """
-- Create tables for StayOra

CREATE TABLE IF NOT EXISTS users (
  id BIGSERIAL PRIMARY KEY,
  username VARCHAR(255) UNIQUE NOT NULL,
  password_hash VARCHAR(255),
  google_id VARCHAR(255) UNIQUE,
  role VARCHAR(20) DEFAULT 'user',
  account_type_request VARCHAR(20) DEFAULT 'user',
  profile_image TEXT,
  email VARCHAR(255),
  phone VARCHAR(20),
  address VARCHAR(500),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  stripe_account_id VARCHAR(255),
  bank_name VARCHAR(255),
  bank_iban VARCHAR(255),
  bank_holder VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS hotels (
  id BIGSERIAL PRIMARY KEY,
  owner_id BIGINT REFERENCES users(id) ON DELETE CASCADE NOT NULL,
  name VARCHAR(255) NOT NULL,
  property_type VARCHAR(50) DEFAULT 'hotel',
  description TEXT,
  address VARCHAR(255),
  city VARCHAR(100),
  country VARCHAR(100),
  stars INT DEFAULT 3,
  main_image TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  total_rooms INT DEFAULT 1,
  max_guests INT DEFAULT 2,
  price_per_night FLOAT,
  avg_rating NUMERIC(2,1) DEFAULT 0,
  review_count INT DEFAULT 0,
  amenities TEXT
);

CREATE TABLE IF NOT EXISTS rooms (
  id BIGSERIAL PRIMARY KEY,
  hotel_id BIGINT REFERENCES hotels(id) ON DELETE SET NULL,
  number INT NOT NULL,
  price FLOAT NOT NULL,
  type VARCHAR(50) NOT NULL,
  beds INT,
  jacuzzi BOOLEAN DEFAULT FALSE,
  image_data TEXT,
  UNIQUE(number)
);

CREATE TABLE IF NOT EXISTS hotel_images (
  id BIGSERIAL PRIMARY KEY,
  hotel_id BIGINT REFERENCES hotels(id) ON DELETE CASCADE NOT NULL,
  image_data TEXT NOT NULL,
  caption VARCHAR(255),
  is_primary BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS reservations (
  id BIGSERIAL PRIMARY KEY,
  room_id BIGINT REFERENCES rooms(id) ON DELETE CASCADE NOT NULL,
  guest VARCHAR(255) NOT NULL,
  user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
  start_date DATE NOT NULL,
  nights INT NOT NULL,
  payment_status VARCHAR(20) DEFAULT 'pending',
  payment_id VARCHAR(255),
  total_price FLOAT
);

CREATE TABLE IF NOT EXISTS property_reservations (
  id BIGSERIAL PRIMARY KEY,
  property_id BIGINT REFERENCES hotels(id) ON DELETE CASCADE NOT NULL,
  guest VARCHAR(255) NOT NULL,
  user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
  start_date DATE NOT NULL,
  nights INT NOT NULL,
  total_price FLOAT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  payment_status VARCHAR(20) DEFAULT 'pending',
  payment_id VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS hotel_reviews (
  id BIGSERIAL PRIMARY KEY,
  hotel_id BIGINT REFERENCES hotels(id) ON DELETE CASCADE NOT NULL,
  user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
  rating NUMERIC(2,1) NOT NULL,
  review_text TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS activities (
  id BIGSERIAL PRIMARY KEY,
  activity TEXT,
  timestamp TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS trending_destinations (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  country VARCHAR(100) DEFAULT 'Bulgaria',
  image_data TEXT,
  property_count INT DEFAULT 0,
  display_order INT DEFAULT 0,
  is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS promotions (
  id BIGSERIAL PRIMARY KEY,
  title VARCHAR(255) NOT NULL,
  description TEXT,
  discount_percent INT DEFAULT 0,
  valid_until DATE,
  image_data TEXT,
  is_active BOOLEAN DEFAULT TRUE
);
"""

if __name__ == '__main__':
    print("Copy the SQL above and run it in your Supabase SQL Editor.")
    print()
    print("=" * 60)
    print(SETUP_SQL)
