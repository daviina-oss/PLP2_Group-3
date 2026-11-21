"""Tests for the service and database layers (in-memory database)."""
import unittest
from datetime import date

from heritage.database import Database
from heritage.service import (
    AuthError, HeritageService, NotFoundError, PermissionDenied,
    ValidationError,
)

TRADITION = {"name": "Intore dance", "region": "Rwanda",
             "category": "dance", "description": "Warrior dance."}


class ServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.service = HeritageService(self.db)
        self.curator = self.service.create_first_curator(
            "curator1", "password123")
        self.contributor = self.service.register("amina", "secret123")

    def tearDown(self):
        self.db.close()

    def add_tradition(self, **overrides):
        data = dict(TRADITION, **overrides)
        return self.service.add_record("tradition", data, self.contributor)


class TestPermissions(ServiceTestCase):
    def test_role_table(self):
        can = HeritageService.can
        for action in ("view", "search", "report"):
            self.assertTrue(can("guest", action))
        self.assertFalse(can("guest", "add"))
        self.assertTrue(can("contributor", "add"))
        self.assertTrue(can("contributor", "update"))
        self.assertFalse(can("contributor", "delete"))
        self.assertTrue(can("curator", "delete"))
        self.assertFalse(can("nobody", "view"))

    def test_guest_cannot_add_update_delete(self):
        rid = self.add_tradition()
        with self.assertRaises(PermissionDenied):
            self.service.add_record("tradition", TRADITION, None)
        with self.assertRaises(PermissionDenied):
            self.service.update_record("tradition", rid, {"name": "X"}, None)
        with self.assertRaises(PermissionDenied):
            self.service.delete_record("tradition", rid, None)

    def test_contributor_cannot_delete(self):
        rid = self.add_tradition()
        with self.assertRaises(PermissionDenied):
            self.service.delete_record("tradition", rid, self.contributor)
        self.assertIsNotNone(self.db.get_record("tradition", rid))

    def test_curator_can_delete(self):
        rid = self.add_tradition()
        self.service.delete_record("tradition", rid, self.curator)
        self.assertIsNone(self.db.get_record("tradition", rid))


class TestRecords(ServiceTestCase):
    def test_add_and_get_tradition(self):
        rid = self.add_tradition(category="DANCE")
        row = self.service.get_record("tradition", rid)
        self.assertEqual(row["name"], "Intore dance")
        self.assertEqual(row["category"], "dance")      # normalised
        self.assertEqual(row["created_by"], "amina")

    def test_required_fields(self):
        for field in ("name", "region", "category"):
            with self.assertRaises(ValidationError, msg=field):
                self.add_tradition(**{field: "   "})

    def test_invalid_category(self):
        with self.assertRaises(ValidationError):
            self.add_tradition(category="sport")

    def test_text_is_trimmed_and_length_limited(self):
        rid = self.add_tradition(name="  Kente  ")
        self.assertEqual(self.service.get_record("tradition", rid)["name"],
                         "Kente")
        with self.assertRaises(ValidationError):
            self.add_tradition(name="x" * 101)
        with self.assertRaises(ValidationError):
            self.add_tradition(description="x" * 501)

    def test_event_with_and_without_tradition(self):
        tid = self.add_tradition()
        eid = self.service.add_record("event", {
            "name": "Showcase", "event_date": "2026-12-12",
            "location": "Kigali", "tradition_id": str(tid)}, self.contributor)
        row = self.service.get_record("event", eid)
        self.assertEqual(row["tradition_name"], "Intore dance")
        eid2 = self.service.add_record("event", {
            "name": "Open day", "event_date": "2026-12-13",
            "location": "Kigali", "tradition_id": ""}, self.contributor)
        self.assertIsNone(
            self.service.get_record("event", eid2)["tradition_id"])

    def test_event_validation(self):
        base = {"name": "E", "event_date": "2026-12-12", "location": "L"}
        for bad_date in ("12/12/2026", "2026-13-01", "2026-02-30", "soon"):
            with self.assertRaises(ValidationError, msg=bad_date):
                self.service.add_record(
                    "event", dict(base, event_date=bad_date), self.contributor)
        for bad_id in ("abc", "0", "-1", "999"):
            with self.assertRaises(ValidationError, msg=bad_id):
                self.service.add_record(
                    "event", dict(base, tradition_id=bad_id), self.contributor)

    def test_unknown_kind_and_field(self):
        with self.assertRaises(ValidationError):
            self.service.list_records("festival")
        with self.assertRaises(ValidationError):
            self.service.validate_field("tradition", "colour", "red")

    def test_update_keeps_unchanged_fields(self):
        rid = self.add_tradition()
        self.service.update_record(
            "tradition", rid, {"region": "East Africa"}, self.contributor)
        row = self.service.get_record("tradition", rid)
        self.assertEqual(row["region"], "East Africa")
        self.assertEqual(row["name"], "Intore dance")

    def test_update_validates_and_does_not_save_bad_data(self):
        rid = self.add_tradition()
        with self.assertRaises(ValidationError):
            self.service.update_record(
                "tradition", rid, {"category": "sport"}, self.contributor)
        self.assertEqual(
            self.service.get_record("tradition", rid)["category"], "dance")

    def test_update_and_delete_missing_record(self):
        with self.assertRaises(NotFoundError):
            self.service.update_record(
                "tradition", 99, {"name": "X"}, self.contributor)
        with self.assertRaises(NotFoundError):
            self.service.delete_record("tradition", 99, self.curator)

    def test_clear_optional_field(self):
        rid = self.add_tradition()
        self.service.update_record(
            "tradition", rid, {"description": ""}, self.contributor)
        self.assertEqual(
            self.service.get_record("tradition", rid)["description"], "")

    def test_deleting_a_tradition_keeps_its_events(self):
        tid = self.add_tradition()
        eid = self.service.add_record("event", {
            "name": "Showcase", "event_date": "2026-12-12",
            "location": "Kigali", "tradition_id": tid}, self.contributor)
        self.service.delete_record("tradition", tid, self.curator)
        row = self.service.get_record("event", eid)
        self.assertIsNone(row["tradition_id"])
        self.assertIsNone(row["tradition_name"])


class TestSearchAndReport(ServiceTestCase):
    def setUp(self):
        super().setUp()
        self.add_tradition()
        self.add_tradition(name="Kente weaving", region="Ghana",
                           category="craft", description="Woven cloth.")
        self.add_tradition(name="Discount 50% day", region="Test_land",
                           category="other", description="")

    def names(self, term):
        return [r["name"] for r in
                self.service.search_records("tradition", term)]

    def test_search_any_text_field_any_case(self):
        self.assertEqual(self.names("RWANDA"), ["Intore dance"])
        self.assertEqual(self.names("woven"), ["Kente weaving"])
        self.assertEqual(self.names("craft"), ["Kente weaving"])
        self.assertEqual(self.names("zzz"), [])

    def test_search_wildcards_are_literal(self):
        self.assertEqual(self.names("%"), ["Discount 50% day"])
        self.assertEqual(self.names("_"), ["Discount 50% day"])
        self.assertEqual(self.names("50%"), ["Discount 50% day"])

    def test_search_sql_injection_is_harmless(self):
        self.assertEqual(self.names("'; DROP TABLE traditions; --"), [])
        self.assertEqual(len(self.service.list_records("tradition")), 3)

    def test_empty_search_rejected(self):
        for term in ("", "   ", None):
            with self.assertRaises(ValidationError):
                self.service.search_records("tradition", term)

    def test_search_events_by_tradition_name(self):
        tid = [r["id"] for r in self.service.list_records("tradition")
               if r["name"] == "Kente weaving"][0]
        self.service.add_record("event", {
            "name": "Gala", "event_date": "2026-12-12", "location": "Kigali",
            "tradition_id": tid}, self.contributor)
        found = self.service.search_records("event", "kente")
        self.assertEqual([r["name"] for r in found], ["Gala"])

    def test_summary(self):
        self.service.add_record("event", {
            "name": "Past", "event_date": "2020-01-01",
            "location": "A"}, self.contributor)
        self.service.add_record("event", {
            "name": "Future", "event_date": "2030-01-01",
            "location": "B"}, self.contributor)
        report = self.service.summary(today=date(2026, 11, 21))
        self.assertEqual(report["traditions"], 3)
        self.assertEqual(report["events"], 2)
        self.assertEqual(report["upcoming_events"], 1)
        self.assertEqual(dict(report["by_category"]),
                         {"dance": 1, "craft": 1, "other": 1})

    def test_group_by_rejects_unknown_column(self):
        with self.assertRaises(ValueError):
            self.db.count_by("tradition", "name; DROP TABLE users")


class TestAccounts(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.service = HeritageService(self.db)

    def tearDown(self):
        self.db.close()

    def test_first_run_setup_only_once(self):
        self.assertTrue(self.service.needs_setup())
        user = self.service.create_first_curator("boss", "longpassword")
        self.assertEqual(user["role"], "curator")
        self.assertFalse(self.service.needs_setup())
        with self.assertRaises(PermissionDenied):
            self.service.create_first_curator("other", "longpassword")

    def test_register_creates_contributor_only(self):
        user = self.service.register("amina", "secret123")
        self.assertEqual(user["role"], "contributor")

    def test_register_validation(self):
        for name in ("ab", "has space", "x" * 21, "bad!", ""):
            with self.assertRaises(ValidationError, msg=name):
                self.service.register(name, "secret123")
        with self.assertRaises(ValidationError):
            self.service.register("amina", "short")
        self.service.register("amina", "secret123")
        with self.assertRaises(ValidationError):
            self.service.register("AMINA", "secret123")   # name taken

    def test_login(self):
        self.service.register("amina", "secret123")
        self.assertEqual(
            self.service.authenticate("amina", "secret123")["role"],
            "contributor")
        self.assertEqual(
            self.service.authenticate("AMINA", "secret123")["username"],
            "amina")
        for creds in (("amina", "wrong"), ("ghost", "secret123"), ("", ""),
                      (None, None)):
            with self.assertRaises(AuthError, msg=creds):
                self.service.authenticate(*creds)

    def test_passwords_are_not_stored_in_plain_text(self):
        self.service.register("amina", "secret123")
        row = self.db.get_user("amina")
        self.assertNotIn("secret123", row["password_hash"])
        self.assertEqual(len(row["salt"]), 32)
        self.service.register("bella", "secret123")
        self.assertNotEqual(row["password_hash"],
                            self.db.get_user("bella")["password_hash"])


if __name__ == "__main__":
    unittest.main()
