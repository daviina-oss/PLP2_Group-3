#!/usr/bin/env python3
"""Start the Heritage command-line application."""
import argparse
import os

from heritage.database import Database
from heritage.menu import HeritageCLI
from heritage.sample_data import load_sample_data
from heritage.service import HeritageService


def main():
    parser = argparse.ArgumentParser(
        description="Heritage: traditions and events")
    parser.add_argument(
        "--db", default=os.environ.get("HERITAGE_DB", "heritage.db"),
        help="path of the SQLite database file (default: heritage.db)")
    parser.add_argument(
        "--demo", action="store_true",
        help="add a few sample records if the database is empty")
    args = parser.parse_args()

    db = Database(args.db)
    try:
        service = HeritageService(db)
        if args.demo:
            load_sample_data(service)
        HeritageCLI(service).run()
    finally:
        db.close()


if __name__ == "__main__":
    main()
