from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from collections.abc import Sequence

from . import __doc__ as description
from .pages import backfill, write_page
from .stores import GcsStore, LocalStore, Store

log = logging.getLogger(__name__)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pipindex", description=description, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--local", action="store_true", help="treat BUCKET as a folder on disk")
    commands = parser.add_subparsers(dest="command", required=True)

    page = commands.add_parser("page", help="write the page of a project folder, such as v2/apache-airflow")
    page.add_argument("bucket")
    page.add_argument("folder", type=lambda value: value.strip("/"))
    page.set_defaults(run=lambda store, args: write_page(store, args.folder))

    backfill_command = commands.add_parser(
        "backfill", help="write the page of each project folder under ROOT, such as v2"
    )
    backfill_command.add_argument("bucket")
    backfill_command.add_argument("root", type=lambda value: value.strip("/"))
    backfill_command.set_defaults(run=lambda store, args: backfill(store, args.root))

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    store: Store = LocalStore(args.bucket) if args.local else GcsStore(args.bucket.strip("/"))

    try:
        args.run(store, args)
    except subprocess.CalledProcessError as e:
        log.error("%s", e.stderr.decode(errors="replace").strip() or e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
