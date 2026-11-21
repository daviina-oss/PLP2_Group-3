"""Service layer: validation, roles and permissions, and the app's rules.

The menu never touches SQL and the database never makes decisions. This layer
sits between them, so every rule lives in exactly one place.
"""
import hashlib
import hmac
import re
import secrets
import sqlite3
from datetime import date, datetime

CATEGORIES = ("dance", "music", "cuisine", "ceremony", "craft",
              "oral tradition", "festival", "other")

# What each role may do. "guest" is a visitor who has not logged in.
ROLE_PERMISSIONS = {
    "guest": {"view", "search", "report"},
    "contributor": {"view", "search", "report", "add", "update"},
    "curator": {"view", "search", "report", "add", "update", "delete"},
}

# (field name, prompt label, required) for every editable field of a record.
FIELDS = {
    "tradition": (
        ("name", "Name", True),
        ("region", "Region or country", True),
        ("category", "Category ({})".format(", ".join(CATEGORIES)), True),
        ("description", "Description", False),
    ),
    "event": (
        ("name", "Event name", True),
        ("event_date", "Date (YYYY-MM-DD)", True),
        ("location", "Location", True),
        ("tradition_id", "Related tradition ID", False),
        ("description", "Description", False),
    ),
}

_MAX_LEN = {"name": 100, "region": 60, "location": 100, "description": 500}
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")
MIN_PASSWORD_LEN = 8
_PBKDF2_ROUNDS = 200000


class ValidationError(ValueError):
    """The user typed something that is not acceptable."""


class PermissionDenied(Exception):
    """The user's role does not allow this action."""


class NotFoundError(LookupError):
    """The record does not exist."""


class AuthError(Exception):
    """Login failed."""


def _hash_password(password, salt_hex):
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex),
        _PBKDF2_ROUNDS).hex()


class HeritageService:
    """All the rules of the Heritage app."""

    def __init__(self, db):
        self.db = db

    # ---------- permissions ----------

    @staticmethod
    def can(role, action):
        """Return True if a role is allowed to perform an action."""
        return action in ROLE_PERMISSIONS.get(role, ())

    def _require(self, user, action):
        role = user["role"] if user else "guest"
        if not self.can(role, action):
            raise PermissionDenied(
                "Your role ({}) is not allowed to {}.".format(role, action))

    # ---------- validation ----------

    @staticmethod
    def _check_kind(kind):
        if kind not in FIELDS:
            raise ValidationError("Unknown record type: {!r}".format(kind))

    def validate_field(self, kind, field, value):
        """Return the cleaned value of one field, or raise ValidationError."""
        self._check_kind(kind)
        required = {f: r for f, _, r in FIELDS[kind]}
        if field not in required:
            raise ValidationError("Unknown field: {!r}".format(field))
        text = "" if value is None else str(value).strip()

        if field == "tradition_id":
            if text == "":
                return None
            if not text.isdigit() or int(text) < 1:
                raise ValidationError(
                    "The tradition ID must be a whole number.")
            if self.db.get_record("tradition", int(text)) is None:
                raise ValidationError(
                    "There is no tradition with ID {}.".format(text))
            return int(text)

        if text == "":
            if required[field]:
                raise ValidationError("This field cannot be empty.")
            return ""
        if field == "category":
            text = text.lower()
            if text not in CATEGORIES:
                raise ValidationError(
                    "Category must be one of: {}.".format(
                        ", ".join(CATEGORIES)))
        elif field == "event_date":
            try:
                datetime.strptime(text, "%Y-%m-%d")
            except ValueError:
                raise ValidationError(
                    "Use the format YYYY-MM-DD, for example 2026-08-07.")
        limit = _MAX_LEN.get(field)
        if limit and len(text) > limit:
            raise ValidationError(
                "Please keep this under {} characters.".format(limit))
        return text

    def _clean_all(self, kind, data):
        self._check_kind(kind)
        return {f: self.validate_field(kind, f, data.get(f))
                for f, _, _ in FIELDS[kind]}

    # ---------- records ----------

    def add_record(self, kind, data, user):
        self._require(user, "add")
        cleaned = self._clean_all(kind, data)
        return self.db.insert_record(
            kind, cleaned, user["username"] if user else "")

    def get_record(self, kind, record_id):
        self._check_kind(kind)
        row = self.db.get_record(kind, record_id)
        if row is None:
            raise NotFoundError(
                "There is no {} with ID {}.".format(kind, record_id))
        return row

    def list_records(self, kind):
        self._check_kind(kind)
        return self.db.list_records(kind)

    def search_records(self, kind, term):
        self._check_kind(kind)
        term = (term or "").strip()
        if not term:
            raise ValidationError("Please type something to search for.")
        return self.db.search_records(kind, term)

    def update_record(self, kind, record_id, changes, user):
        """Change some fields of a record; fields not in changes are kept."""
        self._require(user, "update")
        current = self.get_record(kind, record_id)
        merged = {f: current[f] for f, _, _ in FIELDS[kind]}
        merged.update(changes)
        cleaned = self._clean_all(kind, merged)
        self.db.update_record(kind, record_id, cleaned)
        return cleaned

    def delete_record(self, kind, record_id, user):
        self._require(user, "delete")
        self.get_record(kind, record_id)
        self.db.delete_record(kind, record_id)

    def summary(self, today=None):
        """Numbers for the report screen."""
        today = (today or date.today()).isoformat()
        return {
            "traditions": self.db.count_records("tradition"),
            "events": self.db.count_records("event"),
            "upcoming_events": self.db.count_records(
                "event", upcoming_from=today),
            "by_category": self.db.count_by("tradition", "category"),
            "by_region": self.db.count_by("tradition", "region"),
        }

    # ---------- accounts ----------

    def needs_setup(self):
        """True on the very first run, before any account exists."""
        return self.db.count_users() == 0

    def _create_user(self, username, password, role):
        username = (username or "").strip()
        if not _USERNAME_RE.match(username):
            raise ValidationError(
                "Username must be 3-20 letters, digits or underscores.")
        if len(password or "") < MIN_PASSWORD_LEN:
            raise ValidationError(
                "Password must be at least {} characters.".format(
                    MIN_PASSWORD_LEN))
        salt = secrets.token_hex(16)
        try:
            self.db.add_user(
                username, _hash_password(password, salt), salt, role)
        except sqlite3.IntegrityError:
            raise ValidationError("That username is already taken.")
        return {"username": username, "role": role}

    def create_first_curator(self, username, password):
        """Create the first account (a curator), on a fresh install only."""
        if not self.needs_setup():
            raise PermissionDenied("Setup has already been done.")
        return self._create_user(username, password, "curator")

    def register(self, username, password):
        """Create a contributor account."""
        return self._create_user(username, password, "contributor")

    def authenticate(self, username, password):
        """Return the user (username, role) for valid credentials.

        Raises AuthError otherwise.
        """
        row = self.db.get_user((username or "").strip())
        # Hash even for an unknown user so both failures take the same time.
        salt = row["salt"] if row else "00" * 16
        candidate = _hash_password(password or "", salt)
        if row is None or not hmac.compare_digest(
                candidate, row["password_hash"]):
            raise AuthError("Invalid username or password.")
        return {"username": row["username"], "role": row["role"]}
