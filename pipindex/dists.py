import dataclasses
import email
import hashlib
import logging
import tarfile
import zipfile

from .files import CORE_METADATA_SHA256_KEY, REQUIRES_PYTHON_KEY, SHA256_KEY

log = logging.getLogger(__name__)

CORE_METADATA_SUFFIX = ".metadata"
FILE_CACHE_CONTROL = "public,max-age=31536000,immutable"


def inspect_dist(store, folder, file):
    """Work out a dist's hash, Python requirement and core metadata, and store them on its object."""
    key = f"{folder}/{file.filename}"
    log.info("inspecting %s", key)
    digest = hashlib.sha256()
    try:
        with store.open(key) as content:
            for chunk in iter(lambda: content.read(1 << 20), b""):
                digest.update(chunk)
            content.seek(0)
            core_metadata = read_core_metadata(file.filename, content)
    except (zipfile.BadZipFile, tarfile.TarError, EOFError) as e:
        log.warning("warning: cannot read %s, so its link has no hash: %s", key, e)
        return file

    file = dataclasses.replace(file, sha256=digest.hexdigest())
    if core_metadata:
        file.requires_python = email.message_from_bytes(core_metadata).get("Requires-Python")
    # PEP 658 serves core metadata for wheels only; an sdist's PKG-INFO may not match what it builds.
    if core_metadata and file.filename.endswith(".whl"):
        store.write(key + CORE_METADATA_SUFFIX, core_metadata, "text/plain", FILE_CACHE_CONTROL)
        file.core_metadata_sha256 = hashlib.sha256(core_metadata).hexdigest()

    object_metadata = {
        SHA256_KEY: file.sha256,
        REQUIRES_PYTHON_KEY: file.requires_python,
        CORE_METADATA_SHA256_KEY: file.core_metadata_sha256,
    }
    # Files uploaded with gsutil cp get the bucket's default cache header, so set it here too.
    store.update_object_metadata(key, {k: v for k, v in object_metadata.items() if v}, FILE_CACHE_CONTROL)
    return file


def read_core_metadata(filename, content):
    if filename.endswith((".whl", ".zip")):
        wanted = ".dist-info/METADATA" if filename.endswith(".whl") else "/PKG-INFO"
        with zipfile.ZipFile(content) as archive:
            for member in archive.namelist():
                if member.count("/") == 1 and member.endswith(wanted):
                    return archive.read(member)
    if filename.endswith(".tar.gz"):
        with tarfile.open(fileobj=content) as archive:
            for member in archive:
                if member.name.count("/") == 1 and member.name.endswith("/PKG-INFO"):
                    extracted = archive.extractfile(member)
                    return extracted.read() if extracted else None
    return None
