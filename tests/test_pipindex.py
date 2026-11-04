import base64
import datetime as dt
import functools
import hashlib
import html.parser
import http.server
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
import unittest.mock
import zipfile
from pathlib import Path

from pipindex import dists, files, pages, stores

UTC = dt.timezone.utc
FOLDER = "v2/demo-pkg"

# The pattern astro-cli uses to read upload times from a project page
# (pkg/runtimeversions/astrobuild.go in astronomer/astro-cli).
ASTRO_CLI_LINE = re.compile(r'(?:(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)[^<]*)?<a href="([^"]+)"')


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def metadata_text(name, version, requires_python):
    return f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\nRequires-Python: {requires_python}\n".encode()


def make_wheel(folder, name, version, requires_python=">=3.9"):
    dist = name.replace("-", "_")
    info = f"{dist}-{version}.dist-info"
    files = {
        f"{dist}/__init__.py": b"",
        f"{info}/METADATA": metadata_text(name, version, requires_python),
        f"{info}/WHEEL": b"Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    }
    record = []
    for member, data in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        record.append(f"{member},sha256={digest},{len(data)}")
    record.append(f"{info}/RECORD,,")
    files[f"{info}/RECORD"] = ("\n".join(record) + "\n").encode()
    path = Path(folder) / f"{dist}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as z:
        for member, data in files.items():
            z.writestr(member, data)
    return path


def make_damaged_wheel(folder, name, version):
    member = f"{name.replace('-', '_')}-{version}.dist-info/METADATA"
    path = Path(folder) / f"{name.replace('-', '_')}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(member, metadata_text(name, version, ">=3.9") * 50)
    data = bytearray(path.read_bytes())
    start = 30 + len(member)  # past the local file header, at the deflate stream
    data[start : start + 20] = b"\xff" * 20
    path.write_bytes(data)
    return path


def make_sdist(folder, name, version, requires_python=">=3.10"):
    top = f"{name.replace('-', '_')}-{version}"
    path = Path(folder) / f"{top}.tar.gz"
    pkg_info = metadata_text(name, version, requires_python)
    with tarfile.open(path, "w:gz") as t:
        info = tarfile.TarInfo(f"{top}/PKG-INFO")
        info.size = len(pkg_info)
        t.addfile(info, io.BytesIO(pkg_info))
    return path


class LinkParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = {}
        self._attrs = None

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._attrs = dict(attrs)

    def handle_data(self, data):
        if self._attrs is not None:
            self.links[data] = self._attrs
            self._attrs = None


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.dists = self.tmp / "dists"
        self.dists.mkdir()
        self.store = stores.LocalStore(self.tmp / "bucket")

    def stored(self, filename):
        return self.store.root / FOLDER / filename

    def upload(self, *paths, uploaded=None):
        """Upload files the way CI jobs do, with a plain copy, then write the page."""
        for p in paths:
            self.store.write(f"{FOLDER}/{p.name}", p.read_bytes(), None, None)
        pages.write_page(self.store, FOLDER)
        if uploaded:
            for p in paths:
                self.set_upload_time(p.name, uploaded)

    def set_upload_time(self, filename, uploaded):
        # LocalStore reads a file's upload time from its mtime, so change it and rewrite the page.
        os.utime(self.stored(filename), (uploaded.timestamp(), uploaded.timestamp()))
        pages.write_page(self.store, FOLDER)

    def yank(self, filename, reason):
        self.store.update_object_metadata(f"{FOLDER}/{filename}", {files.YANKED_KEY: reason}, None)
        pages.write_page(self.store, FOLDER)

    def page(self):
        return self.stored("index.html").read_text()

    def links(self):
        parser = LinkParser()
        parser.feed(self.page())
        return parser.links


def past_dev_build_cutoff():
    return dt.datetime.now(UTC) - pages.DEV_BUILD_MAX_AGE - dt.timedelta(days=1)


class PageTest(Fixture):
    def test_wheel_link_gives_hash_upload_time_size_python_and_metadata(self):
        wheel = make_wheel(self.dists, "demo-pkg", "1.0")
        self.upload(wheel, uploaded=dt.datetime(2025, 1, 2, 3, 4, 5, tzinfo=UTC))
        metadata_hash = sha256(self.stored(wheel.name + ".metadata"))
        self.assertEqual(
            self.links()[wheel.name],
            {
                "href": f"{wheel.name}#sha256={sha256(wheel)}",
                "data-upload-time": "2025-01-02T03:04:05Z",
                "data-size": str(wheel.stat().st_size),
                "data-requires-python": ">=3.9",
                "data-core-metadata": f"sha256={metadata_hash}",
                "data-dist-info-metadata": f"sha256={metadata_hash}",
            },
        )

    def test_page_keeps_the_line_layout_astro_cli_reads(self):
        wheel = make_wheel(self.dists, "demo-pkg", "1.0+astro.1")
        self.upload(wheel, uploaded=dt.datetime(2025, 1, 2, 3, 4, 5, tzinfo=UTC))
        self.assertEqual(
            ASTRO_CLI_LINE.findall(self.page()), [("2025-01-02T03:04:05Z", f"{wheel.name}#sha256={sha256(wheel)}")]
        )

    def test_sdist_gets_requires_python_but_no_metadata_file(self):
        sdist = make_sdist(self.dists, "demo-pkg", "2.0")
        self.upload(sdist)
        link = self.links()[sdist.name]
        self.assertEqual(link["data-requires-python"], ">=3.10")
        self.assertNotIn("data-core-metadata", link)
        self.assertFalse(self.stored(sdist.name + ".metadata").exists())

    def test_page_leaves_out_metadata_files_and_links_other_files_plainly(self):
        wheel = make_wheel(self.dists, "demo-pkg", "1.0")
        self.upload(wheel)
        self.store.write(f"{FOLDER}/latest-1.0.build", b"1.0", "text/plain", "no-cache")
        pages.write_page(self.store, FOLDER)
        self.assertEqual(sorted(self.links()), [wheel.name, "latest-1.0.build"])
        self.assertEqual(self.links()["latest-1.0.build"], {"href": "latest-1.0.build"})

    def test_page_leaves_out_old_dev_builds(self):
        old_dev, old_final, new_dev = (
            make_wheel(self.dists, "demo-pkg", v) for v in ("1.0.dev1+astro.1", "1.0+astro.1", "2.0.dev3+astro.1")
        )
        self.upload(old_dev, old_final, uploaded=past_dev_build_cutoff())
        self.upload(new_dev)
        self.assertEqual(sorted(self.links()), [old_final.name, new_dev.name])
        self.assertTrue(self.stored(old_dev.name).exists())

    def test_page_shows_a_yank(self):
        wheel = make_wheel(self.dists, "demo-pkg", "1.0")
        self.upload(wheel)
        self.yank(wheel.name, "broken | build")
        self.assertEqual(self.links()[wheel.name]["data-yanked"], "broken | build")

    def test_page_lists_files_it_cannot_read_without_a_hash(self):
        not_a_zip, wheel = "demo_pkg-0.9-py3-none-any.whl", make_wheel(self.dists, "demo-pkg", "1.0")
        damaged = make_damaged_wheel(self.dists, "demo-pkg", "0.8")
        self.store.write(f"{FOLDER}/{not_a_zip}", b"not a zip", None, None)
        for path in (damaged, wheel):
            self.store.write(f"{FOLDER}/{path.name}", path.read_bytes(), None, None)

        with self.assertLogs("pipindex", "WARNING"):
            pages.write_page(self.store, FOLDER)

        self.assertEqual(self.links()[not_a_zip]["href"], not_a_zip)
        self.assertEqual(self.links()[damaged.name]["href"], damaged.name)
        self.assertEqual(self.links()[wheel.name]["href"], f"{wheel.name}#sha256={sha256(wheel)}")

    def test_inspected_file_cannot_be_overwritten(self):
        wheel = make_wheel(self.dists, "demo-pkg", "1.0")
        self.upload(wheel)
        with self.assertRaises(PermissionError):
            self.store.write(f"{FOLDER}/{wheel.name}", b"other bytes", None, None)

    def test_backfill_writes_each_project_page(self):
        wheel = make_wheel(self.dists, "demo-pkg", "1.0")
        self.store.write(f"{FOLDER}/{wheel.name}", wheel.read_bytes(), None, None)
        pages.backfill(self.store, "v2")
        self.assertEqual(self.links()[wheel.name]["href"], f"{wheel.name}#sha256={sha256(wheel)}")


class HelperTest(unittest.TestCase):
    def test_version_of_reads_wheel_and_sdist_names(self):
        self.assertEqual(files.version_of("apache_airflow-3.3.2+astro.2-py3-none-any.whl"), "3.3.2+astro.2")
        self.assertEqual(files.version_of("apache-airflow-1.10.14+astro.2.tar.gz"), "1.10.14+astro.2")
        self.assertIsNone(files.version_of("notes.zip"))
        self.assertIsNone(files.version_of("broken.whl"))

    def test_gcloud_dict_arg_picks_a_delimiter_no_value_contains(self):
        self.assertEqual(
            stores.gcloud_dict_arg({"yanked": "a|b", "requires-python": ">=3.8,<4"}),
            "^;^yanked=a|b;requires-python=>=3.8,<4",
        )


FAKE_GCLOUD = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
stdin = sys.stdin.read() if "-" in args else None
with open(os.environ["FAKE_GCLOUD_LOG"], "a") as log:
    log.write(json.dumps({"args": args, "stdin": stdin}) + "\\n")
if args[:3] == ["storage", "objects", "list"]:
    print(os.environ["FAKE_GCLOUD_LISTING"])
elif args[:2] == ["storage", "cat"]:
    sys.stdout.buffer.write(open(os.environ["FAKE_GCLOUD_CAT"], "rb").read())
"""


class GcsStoreTest(Fixture):
    def setUp(self):
        super().setUp()
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        gcloud = bin_dir / "gcloud"
        gcloud.write_text(FAKE_GCLOUD.replace("python3", sys.executable, 1))
        gcloud.chmod(0o755)
        self.log = self.tmp / "gcloud.log"
        self.wheel = make_wheel(self.dists, "demo-pkg", "1.0")
        listing = [
            {"name": f"{FOLDER}/", "size": "0", "timeCreated": "2025-01-01T00:00:00.000Z"},
            {"name": f"{FOLDER}/{self.wheel.name}", "size": "100", "timeCreated": "2025-01-02T03:04:05.000Z"},
        ]
        env = {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "FAKE_GCLOUD_LOG": str(self.log),
            "FAKE_GCLOUD_LISTING": json.dumps(listing),
            "FAKE_GCLOUD_CAT": str(self.wheel),
        }
        patcher = unittest.mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)

    def writes(self):
        """Each cp or objects update call, as (target URL, flags, stdin)."""
        writes = []
        for line in self.log.read_text().splitlines():
            call = json.loads(line)
            args = call["args"][1:]
            if args[0] == "cp":
                writes.append((args[-1], args[1:-2], call["stdin"]))
            elif args[:2] == ["objects", "update"]:
                writes.append((args[2], args[3:], call["stdin"]))
        return writes

    def test_page_write_saves_what_it_inspects_then_writes_the_page(self):
        pages.write_page(stores.GcsStore("bucket"), FOLDER)
        url = f"gs://bucket/{FOLDER}/{self.wheel.name}"
        metadata, update, page = self.writes()
        self.assertEqual(
            [metadata[0], update[0], page[0]], [url + ".metadata", url, f"gs://bucket/{FOLDER}/index.html"]
        )
        self.assertIn(f"--cache-control={dists.FILE_CACHE_CONTROL}", metadata[1])
        self.assertIn(f"--cache-control={dists.FILE_CACHE_CONTROL}", update[1])
        self.assertIn("--temporary-hold", update[1])
        self.assertIn(f"--update-custom-metadata=^|^sha256={sha256(self.wheel)}|requires-python=>=3.9|", update[1][-1])
        self.assertIn("--content-type=text/html", page[1])
        self.assertIn(f"{self.wheel.name}#sha256={sha256(self.wheel)}", page[2])
        self.assertNotIn('href=""', page[2])


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


@unittest.skipUnless(shutil.which("uv"), "uv is not installed")
class UvTest(Fixture):
    def setUp(self):
        super().setUp()
        self.old = make_wheel(self.dists, "demo-pkg", "1.0")
        self.new = make_wheel(self.dists, "demo-pkg", "2.0")
        self.upload(self.old, uploaded=dt.datetime(2025, 1, 1, tzinfo=UTC))
        self.upload(self.new, uploaded=dt.datetime(2026, 6, 1, tzinfo=UTC))
        self.project = self.tmp / "project"
        self.project.mkdir()
        self.depend_on("demo-pkg")
        self.cache = self.tmp / "uv-cache"
        server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(self.store.root))
        )
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.index = f"http://127.0.0.1:{server.server_port}/v2/"

    def depend_on(self, requirement):
        (self.project / "pyproject.toml").write_text(
            f'[project]\nname = "p"\nversion = "0"\nrequires-python = ">=3.9"\ndependencies = ["{requirement}"]\n'
        )

    def uv(self, *args, check=True):
        result = subprocess.run(
            [
                "uv",
                *args,
                "--no-config",
                "--default-index",
                self.index,
                "--cache-dir",
                str(self.cache),
                "--python",
                sys.executable,
            ],
            cwd=self.project,
            capture_output=True,
            text=True,
            check=False,
        )
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def locked(self):
        # Python 3.9 has no tomllib, so read the lock with regular expressions.
        lock = (self.project / "uv.lock").read_text()
        block = lock[lock.index('name = "demo-pkg"') :]
        version = re.search(r'version = "([^"]+)"', block)
        assert version
        wheel_hash = re.search(r'wheels = \[\s*\{[^}]*hash = "sha256:([0-9a-f]+)"', block)
        return version.group(1), wheel_hash.group(1) if wheel_hash else None

    def test_lock_records_our_hash(self):
        self.uv("lock")
        self.assertEqual(self.locked(), ("2.0", sha256(self.new)))

    def test_exclude_newer_reads_upload_times(self):
        self.uv("lock", "--exclude-newer", "2025-06-01T00:00:00Z")
        self.assertEqual(self.locked()[0], "1.0")

    def test_yanked_build_is_skipped_by_new_locks_but_installs_from_old_ones(self):
        self.uv("lock")
        self.assertEqual(self.locked()[0], "2.0")
        self.yank(self.new.name, "broken")
        self.uv("sync", "--frozen")
        (self.project / "uv.lock").unlink()
        self.uv("lock", "--refresh")
        self.assertEqual(self.locked()[0], "1.0")

    def test_a_lock_of_a_dev_build_still_syncs_after_it_drops_off_the_page(self):
        dev = make_wheel(self.dists, "demo-pkg", "2.1.dev1")
        self.upload(dev)
        self.depend_on("demo-pkg==2.1.dev1")
        self.uv("lock")
        self.set_upload_time(dev.name, past_dev_build_cutoff())
        self.uv("sync", "--frozen")
        (self.project / "uv.lock").unlink()
        self.assertNotEqual(self.uv("lock", "--refresh", check=False).returncode, 0)


if __name__ == "__main__":
    unittest.main()
