import datetime as dt
import html


def render_page(files):
    # astro reads each line's upload time and link, so the size, time, link layout stays.
    lines = ["<!DOCTYPE html><html><head><title>Astronomer Python Packages</title></head><body><pre>"]
    lines += [f"{human_size(f.size):>10}  {timestamp(f.uploaded)}  {link(f)}" for f in files]
    lines.append("</pre></body></html>")
    return ("\n".join(lines) + "\n").encode()


def link(file):
    href = file.filename
    attributes = {}
    if file.is_dist:
        attributes["data-upload-time"] = timestamp(file.uploaded)
        attributes["data-size"] = str(file.size)
        if file.sha256:
            href += f"#sha256={file.sha256}"
        if file.requires_python:
            attributes["data-requires-python"] = file.requires_python
        if file.core_metadata_sha256:
            attributes["data-core-metadata"] = f"sha256={file.core_metadata_sha256}"
            # The name from before PEP 714, which pip before 23.2 reads.
            attributes["data-dist-info-metadata"] = f"sha256={file.core_metadata_sha256}"
        if file.yanked is not None:
            attributes["data-yanked"] = file.yanked
    rendered = "".join(f' {key}="{html.escape(value)}"' for key, value in attributes.items())
    return f'<a href="{html.escape(href)}"{rendered}>{html.escape(file.filename)}</a>'


def human_size(size):
    if size < 1024:
        return f"{size} B"
    value = float(size)
    for unit in ("KiB", "MiB", "GiB"):
        value /= 1024
        if value < 1024:
            return f"{value:.2f} {unit}"
    return f"{value / 1024:.2f} TiB"


def timestamp(moment):
    return moment.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
