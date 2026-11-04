"""Where the index lives: the GCS bucket, or a folder on disk that stands in for it."""

from __future__ import annotations

import datetime as dt
import io
import json
import posixpath
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import IO, Protocol

from .files import IndexFile


class Store(Protocol):
    def list_files(self, folder: str) -> list[IndexFile]: ...

    def list_folders(self, root: str) -> list[str]: ...

    def open(self, key: str) -> IO[bytes]: ...

    def write(self, key: str, data: bytes, content_type: str | None, cache_control: str | None) -> None: ...

    def update_object_metadata(self, key: str, values: Mapping[str, str], cache_control: str | None) -> None: ...


class GcsStore:
    def __init__(self, bucket: str) -> None:
        self.bucket = bucket

    def list_files(self, folder: str) -> list[IndexFile]:
        listing = self._gcloud_listing("objects", "list", self._url(folder) + "/*", "--raw", "--format=json")
        files = [
            IndexFile.from_object(
                posixpath.basename(o["name"]),
                int(o["size"]),
                # fromisoformat accepts a trailing Z only from Python 3.11.
                dt.datetime.fromisoformat(o["timeCreated"].replace("Z", "+00:00")),
                o.get("metadata") or {},
            )
            for o in json.loads(listing or b"[]")
            if not o["name"].endswith("/")  # an empty placeholder object named after the folder
        ]
        return sorted(files, key=lambda f: f.filename)

    def list_folders(self, root: str) -> list[str]:
        lines = self._gcloud_listing("ls", self._url(root) + "/").decode().splitlines()
        return sorted(posixpath.basename(line.rstrip("/")) for line in lines if line.endswith("/"))

    def open(self, key: str) -> IO[bytes]:
        return io.BytesIO(self._gcloud("cat", self._url(key)))

    def write(self, key: str, data: bytes, content_type: str | None, cache_control: str | None) -> None:
        flags = [f"--content-type={content_type}", f"--cache-control={cache_control}", "--predefined-acl=publicRead"]
        self._gcloud("cp", *flags, "-", self._url(key), stdin=data)

    def update_object_metadata(self, key: str, values: Mapping[str, str], cache_control: str | None) -> None:
        flags = [f"--cache-control={cache_control}", "--update-custom-metadata=" + gcloud_dict_arg(values)]
        self._gcloud("objects", "update", self._url(key), *flags)

    def _url(self, key: str) -> str:
        return f"gs://{self.bucket}/{key}"

    def _gcloud(self, *args: str, stdin: bytes | None = None) -> bytes:
        return subprocess.run(["gcloud", "storage", *args], input=stdin, check=True, capture_output=True).stdout

    def _gcloud_listing(self, *args: str) -> bytes:
        try:
            return self._gcloud(*args)
        except subprocess.CalledProcessError as e:
            if b"matched no objects" in e.stderr:
                return b""
            raise


def gcloud_dict_arg(values: Mapping[str, str]) -> str:
    """Format a dict for a gcloud flag, with a delimiter that no key or value contains."""
    text = "".join(f"{k}{v}" for k, v in values.items())
    delimiter = next(d for d in "|;~@\x1f" if d not in text)
    return f"^{delimiter}^" + delimiter.join(f"{k}={v}" for k, v in values.items())


class LocalStore:
    """A folder on disk that stands in for the bucket, with object metadata in .object-metadata/."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def list_files(self, folder: str) -> list[IndexFile]:
        base = self.root / folder
        files = []
        for child in sorted(base.iterdir()) if base.is_dir() else []:
            if child.is_file():
                stat = child.stat()
                uploaded = dt.datetime.fromtimestamp(stat.st_mtime, dt.timezone.utc)
                object_metadata = self._object_metadata(f"{folder}/{child.name}")
                files.append(IndexFile.from_object(child.name, stat.st_size, uploaded, object_metadata))
        return files

    def list_folders(self, root: str) -> list[str]:
        base = self.root / root
        return sorted(child.name for child in base.iterdir() if child.is_dir()) if base.is_dir() else []

    def open(self, key: str) -> IO[bytes]:
        return (self.root / key).open("rb")

    def write(self, key: str, data: bytes, content_type: str | None, cache_control: str | None) -> None:
        target = self.root / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        # GCS drops an object's custom metadata when the object is overwritten.
        self._metadata_path(key).unlink(missing_ok=True)

    def update_object_metadata(self, key: str, values: Mapping[str, str], cache_control: str | None) -> None:
        merged = {**self._object_metadata(key), **values}
        target = self._metadata_path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(merged))

    def _metadata_path(self, key: str) -> Path:
        return self.root / ".object-metadata" / (key + ".json")

    def _object_metadata(self, key: str) -> dict[str, str]:
        target = self._metadata_path(key)
        return json.loads(target.read_text()) if target.exists() else {}
