import os
import sys
from pathlib import Path

# Add backend directory to sys.path
backend_path = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(backend_path))

from app.db.session import SessionLocal, init_db
from app.db.seed_data import seed_database

def main():
    print("Initializing database schema...")
    init_db()
    db = SessionLocal()
    try:
        print("Seeding database with profiles, tickets, logs, staff accounts, and demo scenarios (S1-S10)...")
        seed_database(db, force_reset=True)
        print("Database successfully seeded!")
    finally:
        db.close()

if __name__ == "__main__":
    main()
