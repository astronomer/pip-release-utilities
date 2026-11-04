from __future__ import annotations

import dataclasses
import datetime as dt
from collections.abc import Mapping

SHA256_KEY = "sha256"
REQUIRES_PYTHON_KEY = "requires-python"
CORE_METADATA_SHA256_KEY = "core-metadata-sha256"
YANKED_KEY = "yanked"


@dataclasses.dataclass(frozen=True)
class IndexFile:
    """A file in a project folder, with the details its link on the page needs."""

    filename: str
    size: int
    uploaded: dt.datetime
    sha256: str | None = None
    requires_python: str | None = None
    core_metadata_sha256: str | None = None
    yanked: str | None = None

    @classmethod
    def from_object(
        cls, filename: str, size: int, uploaded: dt.datetime, object_metadata: Mapping[str, str]
    ) -> IndexFile:
        return cls(
            filename,
            size,
            uploaded,
            sha256=object_metadata.get(SHA256_KEY),
            requires_python=object_metadata.get(REQUIRES_PYTHON_KEY),
            core_metadata_sha256=object_metadata.get(CORE_METADATA_SHA256_KEY),
            yanked=object_metadata.get(YANKED_KEY),
        )

    @property
    def version(self) -> str | None:
        return version_of(self.filename)

    @property
    def is_dist(self) -> bool:
        return self.version is not None

    @property
    def is_dev_build(self) -> bool:
        return self.version is not None and ".dev" in self.version.partition("+")[0]


def version_of(filename: str) -> str | None:
    if filename.endswith(".whl"):
        # name-version(-build)?-python-abi-platform.whl, where the build tag is optional
        parts = filename.removesuffix(".whl").split("-")
        return parts[1] if len(parts) in (5, 6) else None

    for suffix in (".tar.gz", ".zip"):
        if filename.endswith(suffix):
            name, _, version = filename.removesuffix(suffix).rpartition("-")
            return version if name and version else None

    return None
