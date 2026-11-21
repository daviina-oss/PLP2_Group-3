"""Database layer: the only module that talks to SQLite.

Every query is parameterised. Column names that end up in SQL text come from
fixed whitelists in this file, never from user input.
"""
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('contributor', 'curator'))
);

CREATE TABLE IF NOT EXISTS traditions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    region TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    event_date TEXT NOT NULL,
    location TEXT NOT NULL,
    tradition_id INTEGER REFERENCES traditions (id) ON DELETE SET NULL,
    description TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

KINDS = ("tradition", "event")

_TABLE = {"tradition": "traditions", "event": "events"}

EDITABLE_FIELDS = {
    "tradition": ("name", "region", "category", "description"),
    "event": ("name", "event_date", "location", "tradition_id", "description"),
}

_SEARCH_COLUMNS = {
    "tradition": ("name", "region", "category", "description"),
    "event": ("e.name", "e.location", "e.description", "t.name"),
}

_GROUPABLE = {"tradition": ("category", "region"), "event": ()}

_EVENT_SELECT = (
    "SELECT e.*, t.name AS tradition_name FROM events e "
    "LEFT JOIN traditions t ON t.id = e.tradition_id"
)


def _escape_like(term):
    """Escape the LIKE wildcards so a search for '50%' means a literal 50%."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class Database:
    """A thin wrapper around one SQLite connection."""

    def __init__(self, path=":memory:"):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self):
        self.conn.close()

    # ---------- records (traditions and events) ----------

    def insert_record(self, kind, values, created_by=""):
        """Insert a record and return its new id."""
        columns = EDITABLE_FIELDS[kind] + ("created_by",)
        params = [values.get(c) for c in EDITABLE_FIELDS[kind]]
        params.append(created_by)
        sql = "INSERT INTO {} ({}) VALUES ({})".format(
            _TABLE[kind], ", ".join(columns), ", ".join("?" * len(columns)))
        with self.conn:
            return self.conn.execute(sql, params).lastrowid

    def get_record(self, kind, record_id):
        """Return one record as a Row, or None if it does not exist."""
        if kind == "event":
            sql = _EVENT_SELECT + " WHERE e.id = ?"
        else:
            sql = "SELECT * FROM traditions WHERE id = ?"
        return self.conn.execute(sql, (record_id,)).fetchone()

    def list_records(self, kind):
        """Return all records of a kind.

        Traditions are sorted by name and events by date.
        """
        if kind == "event":
            sql = (_EVENT_SELECT +
                   " ORDER BY e.event_date, e.name COLLATE NOCASE")
        else:
            sql = "SELECT * FROM traditions ORDER BY name COLLATE NOCASE"
        return self.conn.execute(sql).fetchall()

    def search_records(self, kind, term):
        """Return the records whose text fields contain term (any case)."""
        pattern = "%" + _escape_like(term) + "%"
        columns = _SEARCH_COLUMNS[kind]
        where = " OR ".join("{} LIKE ? ESCAPE '\\'".format(c) for c in columns)
        if kind == "event":
            sql = _EVENT_SELECT + " WHERE " + where + \
                " ORDER BY e.event_date, e.name COLLATE NOCASE"
        else:
            sql = ("SELECT * FROM traditions WHERE " + where +
                   " ORDER BY name COLLATE NOCASE")
        return self.conn.execute(sql, [pattern] * len(columns)).fetchall()

    def update_record(self, kind, record_id, values):
        """Update the given fields. Return True if a record was changed."""
        fields = [f for f in EDITABLE_FIELDS[kind] if f in values]
        if not fields:
            return False
        sql = "UPDATE {} SET {} WHERE id = ?".format(
            _TABLE[kind], ", ".join("{} = ?".format(f) for f in fields))
        params = [values[f] for f in fields] + [record_id]
        with self.conn:
            return self.conn.execute(sql, params).rowcount > 0

    def delete_record(self, kind, record_id):
        """Delete a record. Return True if a record was removed."""
        sql = "DELETE FROM {} WHERE id = ?".format(_TABLE[kind])
        with self.conn:
            return self.conn.execute(sql, (record_id,)).rowcount > 0

    def count_records(self, kind, upcoming_from=None):
        """Count records. For events, upcoming_from limits to date >= value."""
        sql = "SELECT COUNT(*) FROM {}".format(_TABLE[kind])
        params = ()
        if kind == "event" and upcoming_from is not None:
            sql += " WHERE event_date >= ?"
            params = (upcoming_from,)
        return self.conn.execute(sql, params).fetchone()[0]

    def count_by(self, kind, column):
        """Return [(value, count), ...] grouped by a whitelisted column."""
        if column not in _GROUPABLE[kind]:
            raise ValueError(
                "Cannot group {} records by {}".format(kind, column))
        sql = ("SELECT {c}, COUNT(*) AS n FROM {t} GROUP BY {c} "
               "ORDER BY n DESC, {c} COLLATE NOCASE").format(
                   c=column, t=_TABLE[kind])
        return [(row[0], row[1]) for row in self.conn.execute(sql)]

    # ---------- users ----------

    def add_user(self, username, password_hash, salt, role):
        """Insert a user.

        Raises sqlite3.IntegrityError if the name is already taken.
        """
        sql = ("INSERT INTO users (username, password_hash, salt, role) "
               "VALUES (?, ?, ?, ?)")
        with self.conn:
            return self.conn.execute(
                sql, (username, password_hash, salt, role)).lastrowid

    def get_user(self, username):
        """Return a user Row (name match ignores case), or None."""
        return self.conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)).fetchone()

    def count_users(self):
        return self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
