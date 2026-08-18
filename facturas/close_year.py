from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
from pathlib import Path
import shutil

from .db import connect, create_schema, get_current_year, set_current_year
from .scan import INBOX_PROVIDERS


@dataclass
class MovePlan:
    source: str
    destination: str


@dataclass
class CloseYearReport:
    status: str
    current_year: int
    next_year: int
    print_root: str
    apply: bool
    moves: list[MovePlan] = field(default_factory=list)
    reason: str | None = None


def close_year(print_path: Path, database_path: Path, *, apply: bool = False) -> CloseYearReport:
    print_root, inbox = _resolve_print_root_and_inbox(print_path.expanduser().resolve())
    database_path = database_path.expanduser().resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)

    with connect(database_path) as connection:
        create_schema(connection)
        current_year = get_current_year(connection)

        destination_year = print_root / "archivo" / str(current_year)
        moves = _build_move_plan(inbox, destination_year)
        report = CloseYearReport(
            status="dry_run" if not apply else "applied",
            current_year=current_year,
            next_year=current_year + 1,
            print_root=str(print_root),
            apply=apply,
            moves=moves,
        )
        if not apply:
            return report

        destination_year.mkdir(parents=True, exist_ok=True)
        for provider in sorted(INBOX_PROVIDERS):
            (inbox / provider).mkdir(parents=True, exist_ok=True)
            (destination_year / provider).mkdir(parents=True, exist_ok=True)

        for move in moves:
            Path(move.destination).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(move.source, move.destination)

        with connection:
            set_current_year(connection, current_year + 1)
        return report


def _resolve_print_root_and_inbox(path: Path) -> tuple[Path, Path]:
    if path.name == "inbox":
        print_root = path.parent
        inbox = path
    else:
        print_root = path
        inbox = path / "inbox"
    if print_root.name != "_print":
        raise ValueError("close_year requires _print or _print/inbox")
    if not inbox.is_dir():
        raise ValueError("inbox does not exist")
    return print_root, inbox


def _build_move_plan(inbox: Path, destination_year: Path) -> list[MovePlan]:
    direct_files = sorted(path for path in inbox.iterdir() if path.is_file())
    if direct_files:
        raise ValueError("inbox contains files directly instead of provider subfolders")

    provider_dirs = sorted(path for path in inbox.iterdir() if path.is_dir())
    unknown = [path.name for path in provider_dirs if path.name.lower() not in INBOX_PROVIDERS]
    if unknown:
        raise ValueError(f"inbox contains unknown provider folders: {', '.join(unknown)}")

    moves: list[MovePlan] = []
    for provider_dir in provider_dirs:
        provider = provider_dir.name.lower()
        for source in sorted(path for path in provider_dir.rglob("*") if path.is_file()):
            relative = source.relative_to(provider_dir)
            destination = destination_year / provider / relative
            if destination.exists():
                raise ValueError(f"destination already exists: {destination}")
            moves.append(MovePlan(source=str(source), destination=str(destination)))
    return moves


def main() -> None:
    parser = argparse.ArgumentParser(description="Close the current invoice year.")
    parser.add_argument("print_root", type=Path)
    parser.add_argument("--database", type=Path, default=Path("data/facturas.sqlite3"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    report = close_year(args.print_root, args.database, apply=args.apply)
    print(json.dumps(report, default=lambda value: value.__dict__, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
