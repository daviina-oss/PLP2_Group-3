"""Illustrative sample records for trying the app: python3 main.py --demo"""

_SAMPLE_USER = {"username": "sample_data", "role": "curator"}

TRADITIONS = [
    {"name": "Intore dance", "region": "Rwanda", "category": "dance",
     "description": "A traditional Rwandan warrior dance with drums and "
                    "spear movements, performed at celebrations."},
    {"name": "Umuganura", "region": "Rwanda", "category": "festival",
     "description": "The national harvest festival, a day to share the first "
                    "fruits of the season and give thanks."},
    {"name": "Kente weaving", "region": "Ghana", "category": "craft",
     "description": "Hand-woven cloth made of bright interlocking strips, "
                    "each pattern carrying its own meaning."},
    {"name": "Ethiopian coffee ceremony", "region": "Ethiopia",
     "category": "ceremony",
     "description": "Coffee is roasted, ground and brewed in front of the "
                    "guests, and served in three rounds."},
    {"name": "Gule Wamkulu", "region": "Malawi", "category": "dance",
     "description": "A ritual masked dance of the Chewa people."},
    {"name": "Jollof rice", "region": "West Africa", "category": "cuisine",
     "description": "A one-pot rice dish in a rich tomato base, shared at "
                    "gatherings across the region."},
]

# (event name, date, location, index of the related tradition, description)
EVENTS = [
    ("Umuganura celebration (sample)", "2027-08-06", "Kigali", 1,
     "Community celebration of the harvest."),
    ("Intore dance showcase (sample)", "2026-12-12", "Kigali", 0,
     "An evening of drumming and dance."),
    ("Kente weaving workshop (sample)", "2027-02-20", "Bonwire", 2,
     "Learn the basics of strip weaving."),
]


def load_sample_data(service):
    """Add the sample records, but only if no traditions exist yet."""
    if service.db.count_records("tradition") > 0:
        return False
    ids = [service.add_record("tradition", t, _SAMPLE_USER)
           for t in TRADITIONS]
    for name, event_date, location, index, description in EVENTS:
        service.add_record("event", {
            "name": name, "event_date": event_date, "location": location,
            "tradition_id": ids[index], "description": description,
        }, _SAMPLE_USER)
    return True
