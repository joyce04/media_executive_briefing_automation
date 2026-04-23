#!/usr/bin/env python3
"""Initialize the SQLite database schemas for both pipelines."""
from database.connection import init_db, get_db_path, init_tactics_db, get_tactics_db_path


def main():
    print(f"Initializing daily database at: {get_db_path()}")
    init_db()
    print("Daily database schema created successfully.")

    print(f"Initializing tactics database at: {get_tactics_db_path()}")
    init_tactics_db()
    print("Tactics database schema created successfully.")


if __name__ == "__main__":
    main()
