import io
import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image
from werkzeug.datastructures import FileStorage

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "stayora"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from property_moderation import (
    moderate_property_content,
    prepare_property_images,
    prepare_stored_property_images,
    review_property_submission,
    verify_property_location,
)
from models import Hotel


class PropertyModerationTest(unittest.TestCase):
    def make_png_upload(self, filename="room.png"):
        buffer = io.BytesIO()
        Image.new("RGB", (8, 8), "white").save(buffer, format="PNG")
        return FileStorage(stream=io.BytesIO(buffer.getvalue()), filename=filename)

    def test_normalizes_supported_image_to_jpeg(self):
        images = prepare_property_images([self.make_png_upload()])

        self.assertEqual(len(images), 1)
        self.assertEqual(images[0]["mime_type"], "image/jpeg")
        self.assertTrue(images[0]["bytes"].startswith(b"\xff\xd8"))

    def test_rejects_non_image_upload(self):
        upload = FileStorage(stream=io.BytesIO(b"not an image"), filename="fake.png")

        with self.assertRaises(ValueError):
            prepare_property_images([upload])

    def test_revalidates_stored_property_images(self):
        uploaded = prepare_property_images([self.make_png_upload()])

        stored = prepare_stored_property_images([uploaded[0]["base64"]])

        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["mime_type"], "image/jpeg")
        self.assertTrue(stored[0]["bytes"].startswith(b"\xff\xd8"))

    def test_rejects_invalid_stored_property_image(self):
        with self.assertRaises(ValueError):
            prepare_stored_property_images(["not-base64!"])

    def test_without_gemini_key_requires_owner_action(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            result = review_property_submission(
                "Stay", "Description", "hotel", "123 Main Street", "Sofia", "Bulgaria", []
            )

        self.assertEqual(result["review_status"], "action_required")
        self.assertIn("API key", result["summary"])

    def test_gemini_flag_is_a_review_signal_not_approval(self):
        fake_response = SimpleNamespace(text=json.dumps({
            "flagged": True,
            "categories": ["misleading_image"],
            "summary": "Image may not depict a property.",
        }))
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), patch("property_moderation.Client") as client_class:
            client_class.return_value.models.generate_content.return_value = fake_response
            result = moderate_property_content(
                "Stay", "Description", "hotel", "Address", "Sofia", "Bulgaria",
                [{"bytes": b"jpeg", "mime_type": "image/jpeg"}],
            )

        self.assertEqual(result["status"], "flagged")
        self.assertEqual(result["categories"], ["misleading_image"])
        client_class.return_value.models.generate_content.assert_called_once()

    def test_clear_content_and_matching_location_auto_approves(self):
        with patch("property_moderation.moderate_property_content", return_value={"status": "clear", "summary": "Clear."}), \
             patch("property_moderation.verify_property_location", return_value={"status": "matched", "summary": "Matched."}):
            result = review_property_submission(
                "Stay", "Description", "hotel", "123 Main Street", "Sofia", "Bulgaria", []
            )

        self.assertEqual(result["review_status"], "approved")
        self.assertEqual(result["moderation_status"], "clear")

    def test_flagged_content_is_rejected_without_location_check(self):
        with patch("property_moderation.moderate_property_content", return_value={"status": "flagged", "summary": "Unsafe."}), \
             patch("property_moderation.verify_property_location") as location_check:
            result = review_property_submission(
                "Stay", "Description", "hotel", "123 Main Street", "Sofia", "Bulgaria", []
            )

        self.assertEqual(result["review_status"], "rejected")
        location_check.assert_not_called()

    def test_location_match_rejects_different_street_number(self):
        places_response = {
            "places": [{
                "displayName": {"text": "Grand Hotel"},
                "formattedAddress": "123 Main Street, Sofia, Bulgaria",
            }]
        }
        response = io.BytesIO(json.dumps(places_response).encode("utf-8"))
        with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "test-key"}), \
             patch("property_moderation.urlopen", return_value=response):
            result = verify_property_location(
                "Grand Hotel", "999 Main Street", "Sofia", "Bulgaria"
            )

        self.assertEqual(result["status"], "mismatch")

    def test_location_requires_full_address(self):
        result = verify_property_location("Stay", "", "Sofia", "Bulgaria")

        self.assertEqual(result["status"], "incomplete")

    def test_public_property_search_filters_to_approved(self):
        class Query:
            def __init__(self):
                self.filters = []

            def select(self, *_args, **_kwargs):
                return self

            def eq(self, field, value):
                self.filters.append((field, value))
                return self

            def execute(self):
                return SimpleNamespace(data=[])

        query = Query()
        with patch("models.supabase.table", return_value=query):
            self.assertEqual(Hotel.search(), [])

        self.assertIn(("review_status", "approved"), query.filters)


if __name__ == "__main__":
    unittest.main()
