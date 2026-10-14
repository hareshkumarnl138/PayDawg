"""Clear demo payments and the Notebook so the 3-payment demo can be run again.

Run from the repository root, with the same DATABASE_PATH the server uses:
    python demo_shop/reset_demo.py

Safety: refuses to run unless PAYPAL_MODE=mock (pass --force to wipe other data anyway).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.db import init_db, reset_demo_data  # noqa: E402


def main() -> int:
    if settings.rail_provider != "mock" and "--force" not in sys.argv:
        print("Refusing to reset: PAYPAL_MODE is not 'mock'. Pass --force to wipe this database anyway.")
        return 1
    init_db()
    reset_demo_data()
    print("Demo data cleared in " + settings.database_path + ". You can run demo_shop/send_demo.py again.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
