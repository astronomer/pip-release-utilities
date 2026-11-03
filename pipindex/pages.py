from __future__ import annotations

import concurrent.futures
import datetime as dt
import logging
from typing import TYPE_CHECKING

from .dists import CORE_METADATA_SUFFIX, inspect_dist
from .files import IndexFile
from .render import render_page

if TYPE_CHECKING:
    from .stores import Store

log = logging.getLogger(__name__)

PAGE = "index.html"
PAGE_CACHE_CONTROL = "no-cache,max-age=0"
DEV_BUILD_MAX_AGE = dt.timedelta(days=60)
INSPECT_WORKERS = 8


def write_page(store: Store, folder: str) -> None:
    cutoff = dt.datetime.now(dt.timezone.utc) - DEV_BUILD_MAX_AGE
    files = [f for f in store.list_files(folder) if belongs_on_page(f, cutoff)]

    # Files uploaded with gsutil cp have no stored details yet, so inspect them once.
    uninspected = [f for f in files if f.is_dist and f.sha256 is None]
    with concurrent.futures.ThreadPoolExecutor(INSPECT_WORKERS) as pool:
        inspected = {f.filename: f for f in pool.map(lambda f: inspect_dist(store, folder, f), uninspected)}
    files = [inspected.get(f.filename, f) for f in files]

    store.write(f"{folder}/{PAGE}", render_page(files), "text/html", PAGE_CACHE_CONTROL)
    log.info("wrote %s/%s", folder, PAGE)


def backfill(store: Store, root: str) -> None:
    for project in store.list_folders(root):
        write_page(store, f"{root}/{project}")


def belongs_on_page(file: IndexFile, dev_build_cutoff: dt.datetime) -> bool:
    if file.filename == PAGE or file.filename.endswith(CORE_METADATA_SUFFIX):
        return False
    return not (file.is_dev_build and file.uploaded < dev_build_cutoff)
