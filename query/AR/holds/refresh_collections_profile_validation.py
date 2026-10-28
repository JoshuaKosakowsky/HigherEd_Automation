"""Keep the standalone validation SQL's embedded report synchronized."""
from __future__ import annotations

import argparse
from pathlib import Path


START = "-- BEGIN COLLECTIONS PROFILE SQL"
END = "-- END COLLECTIONS PROFILE SQL"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Refresh the embedded report; default checks only.")
    args = parser.parse_args()
    folder = Path(__file__).resolve().parent
    report = (folder / "collections_student_profile.sql").read_text(encoding="utf-8")
    path = folder / "validate_collections_profile_indicators.sql"
    validation = path.read_text(encoding="utf-8")
    if validation.count(START) != 1 or validation.count(END) != 1:
        parser.exit(1, "Expected one marked collections report block.\n")
    before, _, remaining = validation.partition(START)
    _, _, after = remaining.partition(END)
    if END not in remaining:
        parser.exit(1, "Collections report block markers are out of order.\n")
    refreshed = before + START + "\n" + report.strip().removesuffix(";") + "\n" + END + after
    if args.write:
        path.write_text(refreshed, encoding="utf-8", newline="\n")
        print("Refreshed the collections validation SQL from the shared report.")
    elif validation != refreshed:
        parser.exit(1, "Validation SQL is stale. Run this script with --write and rerun tests.\n")
    else:
        print("Collections validation SQL matches the shared report.")


if __name__ == "__main__":
    main()
