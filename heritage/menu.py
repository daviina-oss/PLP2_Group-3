"""Menu layer: the command-line user journey.

HeritageCLI.run() is the central decision point. From the main menu every
choice leads to one action, and the action always returns to the menu until the
user chooses to exit. The menu only talks to the service layer, never to SQL.
"""
from heritage.service import (
    CATEGORIES, FIELDS, AuthError, NotFoundError, PermissionDenied,
    ValidationError,
)

BANNER = """\
==========================================
   HERITAGE - Traditions and Events
   Keep our cultural heritage alive
=========================================="""

MAIN_MENU = """
--- MAIN MENU ---
1. View records
2. Search records
3. Add a record
4. Update a record
5. Delete a record
6. Summary report
7. Switch user (log in / out)
0. Exit"""

# Plain-words description of each permission, used in the denial messages.
ACTION_LABELS = {"add": "add records", "update": "update records",
                 "delete": "delete records"}


class HeritageCLI:
    """A menu-driven command-line interface for the Heritage service."""

    def __init__(self, service, input_fn=input, output_fn=print):
        self.service = service
        self._input = input_fn
        self._print = output_fn
        self.user = None  # None means a guest (not logged in)

    # ------------------------------------------------------------------
    # The main loop: the central decision point of the user journey
    # ------------------------------------------------------------------

    def run(self):
        """Show the menu again and again until the user chooses to exit."""
        self._print(BANNER)
        try:
            if not self._welcome():
                self._goodbye()
                return
            while True:
                self._show_status()
                self._print(MAIN_MENU)
                choice = self._ask_int("Choose 0-7: ", 0, 7)
                if choice == 0:
                    break
                elif choice == 1:
                    self._view_records()
                elif choice == 2:
                    self._search_records()
                elif choice == 3:
                    self._add_record()
                elif choice == 4:
                    self._update_record()
                elif choice == 5:
                    self._delete_record()
                elif choice == 6:
                    self._show_report()
                else:
                    self.user = None
                    if not self._welcome():
                        break
        except (EOFError, KeyboardInterrupt):
            self._print("")
        self._goodbye()

    # ------------------------------------------------------------------
    # Branch: choose a tradition or an event
    # ------------------------------------------------------------------

    def _pick_record_type(self):
        """Ask which kind of record to work with. Returns None for 'Back'."""
        self._print("\nWhich type of record?")
        self._print("1. Tradition")
        self._print("2. Event")
        self._print("0. Back")
        choice = self._ask_int("Choose 0-2: ", 0, 2)
        if choice == 1:
            return "tradition"
        if choice == 2:
            return "event"
        return None

    # ------------------------------------------------------------------
    # Welcome screen: first-run setup, log in, register, or continue as guest
    # ------------------------------------------------------------------

    def _welcome(self):
        """Return True to enter the app, False if the user chose to exit."""
        if self.service.needs_setup():
            self._first_run_setup()
            if self.user is not None:
                return True   # the new curator is already logged in
        while True:
            self._print("\n--- WELCOME ---")
            self._print("1. Log in")
            self._print("2. Create a contributor account")
            self._print("3. Continue as a guest (read only)")
            self._print("0. Exit")
            choice = self._ask_int("Choose 0-3: ", 0, 3)
            if choice == 0:
                return False
            if choice == 3:
                self.user = None
                return True
            if choice == 1 and self._login():
                return True
            if choice == 2 and self._register():
                return True

    def _first_run_setup(self):
        self._print("\nFirst-time setup: create the curator account.")
        self._print("The curator can add, update and delete records.")
        self._print("(Press Enter at the username to skip and continue "
                    "as a guest.)")
        while True:
            username = self._ask("Curator username: ")
            if username == "":
                return
            password = self._ask("Curator password (min 8 characters): ")
            try:
                self.user = self.service.create_first_curator(
                    username, password)
            except ValidationError as error:
                self._print("  " + str(error))
                continue
            self._print("  Curator account created. You are logged in.")
            return

    def _login(self):
        username = self._ask("Username: ")
        password = self._ask("Password: ")
        try:
            self.user = self.service.authenticate(username, password)
        except AuthError as error:
            self._print("  " + str(error))
            return False
        self._print("  Welcome back, {}!".format(self.user["username"]))
        return True

    def _register(self):
        username = self._ask("Choose a username: ")
        password = self._ask("Choose a password (min 8 characters): ")
        try:
            self.user = self.service.register(username, password)
        except ValidationError as error:
            self._print("  " + str(error))
            return False
        self._print("  Account created. Welcome, {}!".format(
            self.user["username"]))
        return True

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _view_records(self):
        kind = self._pick_record_type()
        if kind is None:
            return
        records = self.service.list_records(kind)
        self._print_table(kind, records)
        if not records:
            return
        raw = self._ask(
            "Type an ID to see its full details (Enter to go back): ")
        if raw == "":
            return
        if not raw.isdigit():
            self._print("  That is not a valid ID.")
            return
        try:
            self._print_details(kind, self.service.get_record(kind, int(raw)))
        except NotFoundError as error:
            self._print("  " + str(error))

    def _search_records(self):
        kind = self._pick_record_type()
        if kind is None:
            return
        term = self._ask("Search for: ")
        try:
            records = self.service.search_records(kind, term)
        except ValidationError as error:
            self._print("  " + str(error))
            return
        self._print_table(kind, records)

    def _add_record(self):
        # Permission check first: the user is sent away before any question.
        if not self._allowed("add"):
            return
        kind = self._pick_record_type()
        if kind is None:
            return
        data = {}
        for field, label, required in FIELDS[kind]:
            data[field] = self._ask_field(kind, field, label, required)
        try:
            new_id = self.service.add_record(kind, data, self.user)
        except (ValidationError, PermissionDenied) as error:
            self._print("  Could not save: {}".format(error))
            return
        self._print("  Saved! The new {} has ID {}.".format(kind, new_id))

    def _update_record(self):
        # Permission check first: the user is sent away before any question.
        if not self._allowed("update"):
            return
        kind = self._pick_record_type()
        if kind is None:
            return
        record = self._ask_existing_record(kind, "update")
        if record is None:
            return
        self._print("Press Enter to keep the current value. "
                    "Type - to clear an optional field.")
        changes = {}
        for field, label, required in FIELDS[kind]:
            current = record[field]
            shown = "" if current is None else current
            while True:
                raw = self._ask("{} [{}]: ".format(label, shown))
                if raw == "":
                    break
                if raw == "-" and not required:
                    changes[field] = ""
                    break
                try:
                    changes[field] = self.service.validate_field(
                        kind, field, raw)
                    break
                except ValidationError as error:
                    self._print("  " + str(error))
        if not changes:
            self._print("  Nothing was changed.")
            return
        try:
            self.service.update_record(kind, record["id"], changes, self.user)
        except (ValidationError, PermissionDenied, NotFoundError) as error:
            self._print("  Could not update: {}".format(error))
            return
        self._print("  Updated {} {}.".format(kind, record["id"]))

    def _delete_record(self):
        # Permission check first: the user is sent away before any question.
        if not self._allowed("delete"):
            return
        kind = self._pick_record_type()
        if kind is None:
            return
        record = self._ask_existing_record(kind, "delete")
        if record is None:
            return
        answer = self._ask(
            "Delete '{}' for good? Type yes to confirm: ".format(
                record["name"])).lower()
        if answer != "yes":
            self._print("  Cancelled. Nothing was deleted.")
            return
        try:
            self.service.delete_record(kind, record["id"], self.user)
        except (PermissionDenied, NotFoundError) as error:
            self._print("  Could not delete: {}".format(error))
            return
        self._print("  Deleted {} {}.".format(kind, record["id"]))

    def _show_report(self):
        report = self.service.summary()
        self._print("\n--- SUMMARY REPORT ---")
        self._print("Traditions recorded : {}".format(report["traditions"]))
        self._print("Events recorded     : {}".format(report["events"]))
        self._print("Upcoming events     : {}".format(
            report["upcoming_events"]))
        if report["by_category"]:
            self._print("\nTraditions by category:")
            for name, count in report["by_category"]:
                self._print("  {:<16} {}".format(name, count))
        if report["by_region"]:
            self._print("\nTraditions by region:")
            for name, count in report["by_region"]:
                self._print("  {:<16} {}".format(name, count))

    # ------------------------------------------------------------------
    # Permission check
    # ------------------------------------------------------------------

    def _role(self):
        return self.user["role"] if self.user else "guest"

    def _allowed(self, action):
        """True if the current role may do this, else explain and say no."""
        if self.service.can(self._role(), action):
            return True
        self._print("\n  Permission denied: your role ({}) cannot {}.".format(
            self._role(), ACTION_LABELS[action]))
        if self.user is None:
            self._print("  Log in with an account (option 7) to continue.")
        else:
            self._print("  Ask a curator to do this for you.")
        return False

    # ------------------------------------------------------------------
    # Input helpers
    # ------------------------------------------------------------------

    def _ask(self, prompt):
        return self._input(prompt).strip()

    def _ask_int(self, prompt, low, high):
        """Keep asking until the user types a whole number from low to high."""
        while True:
            try:
                value = int(self._ask(prompt))
            except ValueError:
                self._print(
                    "  Please type a whole number from {} to {}.".format(
                        low, high))
                continue
            if low <= value <= high:
                return value
            self._print("  Please choose a number from {} to {}.".format(
                low, high))

    def _ask_field(self, kind, field, label, required):
        """Ask for one field until the service accepts the value."""
        suffix = "" if required else " (optional, Enter to skip)"
        while True:
            raw = self._ask("{}{}: ".format(label, suffix))
            try:
                return self.service.validate_field(kind, field, raw)
            except ValidationError as error:
                self._print("  " + str(error))

    def _ask_existing_record(self, kind, verb):
        """List the records, ask for an ID, return that record (or None)."""
        records = self.service.list_records(kind)
        if not records:
            self._print("  There are no {} records yet.".format(kind))
            return None
        self._print_table(kind, records)
        raw = self._ask("ID of the {} to {} (Enter to cancel): ".format(
            kind, verb))
        if raw == "":
            return None
        if not raw.isdigit():
            self._print("  That is not a valid ID.")
            return None
        try:
            return self.service.get_record(kind, int(raw))
        except NotFoundError as error:
            self._print("  " + str(error))
            return None

    # ------------------------------------------------------------------
    # Output helpers
    # ------------------------------------------------------------------

    def _show_status(self):
        if self.user:
            self._print("\nLogged in as {} ({})".format(
                self.user["username"], self.user["role"]))
        else:
            self._print("\nBrowsing as a guest (read only)")

    def _print_table(self, kind, records):
        if not records:
            self._print("\n  No {} records found.".format(kind))
            return
        if kind == "tradition":
            self._print("\n{:<4} {:<28} {:<18} {}".format(
                "ID", "Name", "Region", "Category"))
            for r in records:
                self._print("{:<4} {:<28} {:<18} {}".format(
                    r["id"], _cut(r["name"], 28), _cut(r["region"], 18),
                    r["category"]))
        else:
            self._print("\n{:<4} {:<11} {:<26} {:<18} {}".format(
                "ID", "Date", "Event", "Location", "Tradition"))
            for r in records:
                self._print("{:<4} {:<11} {:<26} {:<18} {}".format(
                    r["id"], r["event_date"], _cut(r["name"], 26),
                    _cut(r["location"], 18), r["tradition_name"] or "-"))
        self._print("({} found)".format(len(records)))

    def _print_details(self, kind, record):
        self._print("\n--- {} #{} ---".format(kind.upper(), record["id"]))
        for field, label, _ in FIELDS[kind]:
            value = record[field]
            if field == "tradition_id":
                label, value = "Related tradition", record["tradition_name"]
            if field == "category":
                label = "Category"
            self._print("{:<18}: {}".format(
                label.split(" (")[0], value or "-"))
        self._print("{:<18}: {}".format(
            "Added by", record["created_by"] or "-"))
        self._print("{:<18}: {}".format("Added on", record["created_at"]))

    def _goodbye(self):
        self._print("\nThank you for keeping our heritage alive. Goodbye!")


def _cut(text, width):
    """Shorten text to fit a table column."""
    text = str(text)
    return text if len(text) <= width else text[:width - 3] + "..."
