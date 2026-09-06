"""Prompt evaluation harness.

    uv run python scripts/eval.py                     # offline: free, no model
    uv run python scripts/eval.py run --live          # spends free-tier quota
    uv run python scripts/eval.py run --live --kind refusal --limit 3
    uv run python scripts/eval.py compare OLD.json NEW.json
    uv run python scripts/eval.py list

The pipeline's own tests replace the agent stages with fakes, which is what
makes them fast and offline — and also blind to whether an edit to
`agents/prompts.py` helped or hurt. This is the other half.

Offline is the default, and deliberately so: it validates every fixture, replays
the recorded tool responses through the real tools, and checks the prompt guards
without touching a model. Run it on every prompt edit. `--live` adds the model
calls, prints what they will cost, and asks before spending anything.

The workflow this exists for:

    uv run python scripts/eval.py run --live --label before
    # edit agents/prompts.py
    uv run python scripts/eval.py run --live --label after
    uv run python scripts/eval.py compare evals/runs/<before>.json evals/runs/<after>.json

`compare` exits non-zero if any case or guard regressed, so it can gate a commit.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from evalkit import manifest as manifest_mod
from evalkit import report as report_mod
from evalkit import runner

DEFAULT_MANIFEST = ROOT / "evals" / "manifest.json"
DEFAULT_RUNS = ROOT / "evals" / "runs"

#: Free-tier primary allowance, for the warning before a live run. Roughly a
#: day's worth on the tiers this project targets; it is a signpost, not a limit
#: the harness enforces, because the provider is the only thing that knows.
PRIMARY_BUDGET_PER_DAY = 20


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv if argv is not None else sys.argv[1:])
    if args.command == "compare":
        return _compare(args)
    if args.command == "list":
        return _list(args)
    return _run(args)


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="eval.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="run the eval (offline unless --live)")
    _add_selection(run)
    run.add_argument(
        "--live",
        action="store_true",
        help="call the model. Costs metered free-tier quota; prints the bill first.",
    )
    run.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    run.add_argument(
        "--rpm",
        type=int,
        default=runner.DEFAULT_RPM,
        help=(
            "requests a minute to stay under while running live. The corroboration "
            "graph makes four calls at once, so back-to-back cases trip a per-minute "
            "free-tier cap long before the daily one. 0 disables the pacing."
        ),
    )
    run.add_argument("--label", default="", help="name this run, for the saved filename")
    run.add_argument("--out", type=Path, default=DEFAULT_RUNS, help="where to write the run file")
    run.add_argument("--no-save", action="store_true", help="print the report, write nothing")
    run.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help="an earlier run file to compare against as soon as this one finishes",
    )

    compare = sub.add_parser("compare", help="diff two run files")
    compare.add_argument("before", type=Path)
    compare.add_argument("after", type=Path)

    listing = sub.add_parser("list", help="show the cases and guards in a manifest")
    _add_selection(listing)

    # No subcommand means `run`, which offline is the free one. The harness has
    # to be trivial to invoke or it will not be invoked. The default has to be
    # applied before parsing rather than after: argparse rejects an unknown
    # option against the top-level parser and exits, so `eval.py --no-save`
    # never reaches a second attempt.
    if not argv or argv[0] not in {"run", "compare", "list"}:
        argv = ["run", *argv]
    return parser.parse_args(argv)


def _add_selection(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--case", action="append", default=[], metavar="ID", help="run only this case (repeatable)"
    )
    parser.add_argument(
        "--kind",
        action="append",
        default=[],
        choices=list(manifest_mod.KINDS),
        help="run only this kind of case (repeatable)",
    )
    parser.add_argument("--limit", type=int, default=0, help="run at most this many cases")


def _load(args: argparse.Namespace):
    book = manifest_mod.load(args.manifest)
    return book, book.select(ids=args.case, kinds=args.kind, limit=args.limit)


def _list(args: argparse.Namespace) -> int:
    book, cases = _load(args)
    print(f"{book.name} — {book.description}")
    print(f"{len(cases)} case(s) selected of {len(book.cases)}, {len(book.guards)} guard(s)\n")
    for case in cases:
        runnable, why = case.runnable
        mark = " " if runnable else "!"
        tag = " [synthetic]" if case.synthetic else ""
        print(f"{mark} {case.id:<26} {case.kind:<15}{tag}")
        print(f"    {case.why}")
        if not runnable:
            print(f"    would skip: {why}")
    cost = manifest_mod.projected_calls([c for c in cases if c.runnable[0]])
    print(f"\nA live run of this selection: {cost['primary']} primary, {cost['fast']} fast calls.")
    return 0


def _run(args: argparse.Namespace) -> int:
    book, cases = _load(args)
    if not cases:
        print("No cases matched the selection.", file=sys.stderr)
        return 2

    if args.live:
        if not _confirm(cases, args.yes):
            print("Nothing spent.")
            return 1
        run = asyncio.run(runner.live(book, cases, rpm=args.rpm))
    else:
        run = runner.offline(book, cases)

    print(report_mod.render(run))

    if not args.no_save:
        path = report_mod.save(run, args.out, args.label)
        print(f"\nRun written to {path}")

    exit_code = _exit_code(run)

    if args.baseline:
        print()
        text, regressed = report_mod.compare(report_mod.load(args.baseline), run)
        print(text)
        exit_code = max(exit_code, 1 if regressed else 0)

    return exit_code


def _exit_code(run: dict) -> int:
    failed = [c for c in run["cases"] if c["status"] in ("fail", "error")]
    guards = [g for g in run["guards"] if not g["passed"]]
    return 1 if failed or guards else 0


def _confirm(cases: list, yes: bool) -> bool:
    """Show the bill before spending it.

    Inference is the only running cost this project has, and the primary tier's
    free allowance is about a report and a half a day. A harness that quietly
    burned it would get switched off, so the cost is stated first, every time.
    """
    runnable = [c for c in cases if c.runnable[0]]
    skipped = len(cases) - len(runnable)
    cost = manifest_mod.projected_calls(runnable)

    tail = f", skipping {skipped}." if skipped else "."
    print(f"About to run {len(runnable)} case(s) live{tail}")
    print(f"  primary calls: {cost['primary']}   (free-tier allowance is around "
          f"{PRIMARY_BUDGET_PER_DAY} a day)")
    print(f"  fast calls:    {cost['fast']}")
    if cost["primary"] > PRIMARY_BUDGET_PER_DAY:
        print("  WARNING: this selection alone exceeds a day's primary allowance.")
        print("           Narrow it with --kind or --limit, or split it over two days.")
    if yes:
        return True
    if not sys.stdin.isatty():
        print("  Not a terminal, and --yes was not given. Refusing to spend quota.")
        return False
    return input("Proceed? [y/N] ").strip().lower() == "y"


def _compare(args: argparse.Namespace) -> int:
    text, regressed = report_mod.compare(
        report_mod.load(args.before), report_mod.load(args.after)
    )
    print(text)
    return 1 if regressed else 0


if __name__ == "__main__":
    raise SystemExit(main())
