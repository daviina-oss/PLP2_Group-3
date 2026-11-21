"""Tests for the menu layer, driven by scripted keyboard input."""
import unittest

from heritage.database import Database
from heritage.menu import HeritageCLI
from heritage.service import HeritageService

TRADITION = {"name": "Intore dance", "region": "Rwanda",
             "category": "dance", "description": "Warrior dance."}


class Session:
    """Stands in for the keyboard and the screen."""

    def __init__(self, inputs):
        self.inputs = list(inputs)
        self.prompts = []
        self.lines = []

    def input(self, prompt=""):
        self.prompts.append(prompt)
        if not self.inputs:
            raise EOFError          # like pressing Ctrl+D at the keyboard
        return self.inputs.pop(0)

    def print(self, *args):
        self.lines.append(" ".join(str(a) for a in args))

    @property
    def text(self):
        return "\n".join(self.lines)


class MenuTestCase(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.service = HeritageService(self.db)
        self.curator = self.service.create_first_curator(
            "curator1", "password123")
        self.service.register("amina", "secret123")
        self.tid = self.service.add_record(
            "tradition", TRADITION, self.curator)

    def tearDown(self):
        self.db.close()

    def run_cli(self, inputs):
        session = Session(inputs)
        cli = HeritageCLI(self.service, session.input, session.print)
        cli.run()
        return session, cli

    # shortcuts for the welcome screen
    GUEST = ["3"]
    CURATOR = ["1", "curator1", "password123"]
    CONTRIBUTOR = ["1", "amina", "secret123"]


class TestStartAndExit(MenuTestCase):
    def test_exit_from_welcome(self):
        session, _ = self.run_cli(["0"])
        self.assertIn("Goodbye", session.text)
        self.assertNotIn("MAIN MENU", session.text)

    def test_guest_then_exit(self):
        session, cli = self.run_cli(self.GUEST + ["0"])
        self.assertIn("Browsing as a guest", session.text)
        self.assertIn("Goodbye", session.text)
        self.assertIsNone(cli.user)

    def test_end_of_input_exits_cleanly(self):
        session, _ = self.run_cli(self.GUEST)     # then EOF
        self.assertIn("Goodbye", session.text)

    def test_menu_rejects_bad_choices(self):
        session, _ = self.run_cli(self.GUEST + ["abc", "", "9", "-1", "0"])
        self.assertEqual(session.text.count("Please type a whole number"), 2)
        self.assertEqual(session.text.count("Please choose a number"), 2)
        self.assertIn("Goodbye", session.text)

    def test_first_run_setup_creates_curator_and_logs_in(self):
        db = Database(":memory:")
        service = HeritageService(db)
        session = Session(["boss", "short", "boss", "longpassword", "0"])
        cli = HeritageCLI(service, session.input, session.print)
        cli.run()
        self.assertIn("First-time setup", session.text)
        self.assertEqual(cli.user["role"], "curator")
        self.assertFalse(service.needs_setup())
        # straight into the main menu, with no second login screen
        self.assertNotIn("--- WELCOME ---", session.text)
        self.assertIn("Logged in as boss (curator)", session.text)
        self.assertIn("MAIN MENU", session.text)
        self.assertEqual(session.inputs, [])
        db.close()

    def test_first_run_setup_can_be_skipped(self):
        db = Database(":memory:")
        session = Session(["", "3", "0"])
        cli = HeritageCLI(HeritageService(db), session.input, session.print)
        cli.run()
        self.assertIsNone(cli.user)
        db.close()


class TestLogin(MenuTestCase):
    def test_login_success_and_wrong_password(self):
        session, cli = self.run_cli(
            ["1", "amina", "wrong"] + self.CONTRIBUTOR + ["0"])
        self.assertIn("Invalid username or password", session.text)
        self.assertEqual(cli.user["username"], "amina")
        self.assertIn("Logged in as amina (contributor)", session.text)

    def test_register_new_account(self):
        session, cli = self.run_cli(
            ["2", "ab", "pw", "2", "bella", "password99", "0"])
        self.assertIn("Username must be", session.text)
        self.assertEqual(cli.user["role"], "contributor")

    def test_switch_user(self):
        session, cli = self.run_cli(
            self.CONTRIBUTOR + ["7"] + self.CURATOR + ["0"])
        self.assertEqual(cli.user["username"], "curator1")

    def test_switch_user_then_exit_from_welcome(self):
        session, _ = self.run_cli(self.GUEST + ["7", "0"])
        self.assertIn("Goodbye", session.text)


class TestPermissionChecks(MenuTestCase):
    """Denied users are sent back BEFORE being asked for any input."""

    def test_guest_is_denied_add_update_delete(self):
        session, _ = self.run_cli(self.GUEST + ["3", "4", "5", "0"])
        self.assertEqual(session.text.count("Permission denied"), 3)
        self.assertIn("Log in with an account", session.text)
        self.assertNotIn("Which type of record?", session.text)
        self.assertEqual(session.inputs, [])      # nothing left unused

    def test_contributor_is_denied_delete_only(self):
        session, _ = self.run_cli(self.CONTRIBUTOR + ["5", "0"])
        self.assertEqual(session.text.count("Permission denied"), 1)
        self.assertIn("cannot delete records", session.text)
        self.assertIn("Ask a curator", session.text)
        self.assertNotIn("Which type of record?", session.text)
        self.assertEqual(self.service.get_record(
            "tradition", self.tid)["name"], "Intore dance")

    def test_contributor_is_allowed_to_reach_add_and_update(self):
        session, _ = self.run_cli(self.CONTRIBUTOR + ["3", "0", "4", "0", "0"])
        self.assertNotIn("Permission denied", session.text)
        self.assertEqual(session.text.count("Which type of record?"), 2)


class TestPickRecordType(MenuTestCase):
    def pick(self, inputs):
        session = Session(inputs)
        cli = HeritageCLI(self.service, session.input, session.print)
        return cli._pick_record_type(), session

    def test_choices(self):
        self.assertEqual(self.pick(["1"])[0], "tradition")
        self.assertEqual(self.pick(["2"])[0], "event")
        self.assertIsNone(self.pick(["0"])[0])

    def test_bad_input_is_asked_again(self):
        kind, session = self.pick(["x", "7", "2"])
        self.assertEqual(kind, "event")
        self.assertEqual(len(session.prompts), 3)


class TestAddUpdateDelete(MenuTestCase):
    def test_add_tradition_with_reprompts(self):
        session, _ = self.run_cli(self.CONTRIBUTOR + [
            "3", "1",
            "", "Kente weaving",            # empty name is refused once
            "Ghana",
            "sport", "craft",               # bad category is refused once
            "Woven cloth",
            "0"])
        self.assertIn("This field cannot be empty", session.text)
        self.assertIn("Category must be one of", session.text)
        self.assertIn("Saved!", session.text)
        found = self.service.search_records("tradition", "kente")
        self.assertEqual(found[0]["created_by"], "amina")

    def test_add_event_with_date_and_tradition_checks(self):
        session, _ = self.run_cli(self.CONTRIBUTOR + [
            "3", "2", "Showcase",
            "12/12/2026", "2026-12-12",     # bad date, then good
            "Kigali",
            "999", str(self.tid),           # unknown tradition, then real
            "",
            "0"])
        self.assertIn("Use the format YYYY-MM-DD", session.text)
        self.assertIn("There is no tradition with ID 999", session.text)
        event = self.service.list_records("event")[0]
        self.assertEqual(event["tradition_name"], "Intore dance")

    def test_add_back_out_at_type_choice(self):
        session, _ = self.run_cli(self.CONTRIBUTOR + ["3", "0", "0"])
        self.assertEqual(len(self.service.list_records("tradition")), 1)

    def test_update_keep_change_and_clear(self):
        self.run_cli(self.CONTRIBUTOR + [
            "4", "1", str(self.tid),
            "",                 # name: keep
            "East Africa",      # region: change
            "",                 # category: keep
            "-",                # description: clear
            "0"])
        row = self.service.get_record("tradition", self.tid)
        self.assertEqual(row["name"], "Intore dance")
        self.assertEqual(row["region"], "East Africa")
        self.assertEqual(row["category"], "dance")
        self.assertEqual(row["description"], "")

    def test_update_with_nothing_changed(self):
        session, _ = self.run_cli(self.CONTRIBUTOR + [
            "4", "1", str(self.tid), "", "", "", "", "0"])
        self.assertIn("Nothing was changed", session.text)

    def test_update_refuses_bad_value_then_accepts_good(self):
        session, _ = self.run_cli(self.CONTRIBUTOR + [
            "4", "1", str(self.tid), "", "", "sport", "music", "", "0"])
        self.assertIn("Category must be one of", session.text)
        self.assertEqual(self.service.get_record(
            "tradition", self.tid)["category"], "music")

    def test_update_unknown_id_and_non_number(self):
        session, _ = self.run_cli(self.CONTRIBUTOR + [
            "4", "1", "99", "4", "1", "abc", "4", "1", "", "0"])
        self.assertIn("There is no tradition with ID 99", session.text)
        self.assertIn("That is not a valid ID", session.text)

    def test_update_with_no_records(self):
        self.db.delete_record("tradition", self.tid)
        session, _ = self.run_cli(self.CONTRIBUTOR + ["4", "1", "0"])
        self.assertIn("There are no tradition records yet", session.text)

    def test_delete_needs_confirmation(self):
        session, _ = self.run_cli(self.CURATOR + [
            "5", "1", str(self.tid), "no", "0"])
        self.assertIn("Cancelled", session.text)
        self.assertIsNotNone(self.db.get_record("tradition", self.tid))

    def test_curator_deletes_after_confirming(self):
        session, _ = self.run_cli(self.CURATOR + [
            "5", "1", str(self.tid), "YES", "0"])
        self.assertIn("Deleted tradition", session.text)
        self.assertIsNone(self.db.get_record("tradition", self.tid))


class TestViewSearchReport(MenuTestCase):
    def test_view_list_and_details(self):
        session, _ = self.run_cli(self.GUEST + ["1", "1", str(self.tid), "0"])
        self.assertIn("Intore dance", session.text)
        self.assertIn("TRADITION #1", session.text)
        self.assertIn("Warrior dance.", session.text)
        self.assertIn("curator1", session.text)

    def test_view_event_shows_tradition_name(self):
        self.service.add_record("event", {
            "name": "Showcase", "event_date": "2026-12-12",
            "location": "Kigali", "tradition_id": self.tid}, self.curator)
        session, _ = self.run_cli(self.GUEST + ["1", "2", "", "0"])
        self.assertIn("2026-12-12", session.text)
        self.assertIn("Intore dance", session.text)

    def test_view_empty_and_bad_id(self):
        session, _ = self.run_cli(self.GUEST + ["1", "2", "1", "1", "x", "0"])
        self.assertIn("No event records found", session.text)
        self.assertIn("That is not a valid ID", session.text)

    def test_view_unknown_id(self):
        session, _ = self.run_cli(self.GUEST + ["1", "1", "42", "0"])
        self.assertIn("There is no tradition with ID 42", session.text)

    def test_search(self):
        session, _ = self.run_cli(self.GUEST + [
            "2", "1", "rwanda", "2", "1", "nothing-matches", "0"])
        self.assertIn("(1 found)", session.text)
        self.assertIn("No tradition records found", session.text)

    def test_empty_search_is_refused(self):
        session, _ = self.run_cli(self.GUEST + ["2", "1", "   ", "0"])
        self.assertIn("Please type something to search for", session.text)

    def test_report(self):
        session, _ = self.run_cli(self.GUEST + ["6", "0"])
        self.assertIn("Traditions recorded : 1", session.text)
        self.assertIn("dance", session.text)
        self.assertIn("Rwanda", session.text)


if __name__ == "__main__":
    unittest.main()
