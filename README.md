# pip-release-utilities

Tools to publish to pip.astronomer.io, a static package index in the `pip.astronomer.io` GCS bucket.

Each project folder, such as `v2/apache-airflow`, holds the files and an `index.html` page (PEP 503). Each link on the page gives:

- the file's sha256 hash, so locks record it
- `data-upload-time` and `data-size`, so `exclude-newer` works in uv
- `data-requires-python`
- `data-core-metadata`, which points at a `<wheel>.metadata` file (PEP 658), so resolvers read a wheel's dependencies without a download of the wheel
- `data-yanked`, for a yanked file (PEP 592)

Each line keeps the old layout, size then upload time then link, because `astro` reads the upload times from it.

The page leaves out dev builds more than 60 days old, such as `3.3.2.dev9+astro.1`. The file stays in the bucket, so `uv sync` still installs it from a `uv.lock` that already records it. Anything that resolves again fails: `uv lock`, `uv add`, or a requirements file that pins the dev build. A dev build drops off at the first page write for its folder after it turns 60 days old.

The tool works out a file's hash, Python requirement and metadata once, and stores them as custom metadata on the file's GCS object. Page writes read that metadata, so they do not download the files again.

A file never changes once uploaded, so files and `.metadata` files get `Cache-Control: public,max-age=31536000,immutable`. Pages get `no-cache`.

## How pip.astronomer.io is served

A Google Cloud load balancer with Cloud CDN serves the bucket. Its URL map gives the index two roots:

| Root | A project in the bucket | Any other name | Use it |
|---|---|---|---|
| `/v2/` | the project's page | a 302 to `https://pypi.org/simple/<name>/` | as the only index, so that pip or uv gets other packages from PyPI |
| `/astro/` | the same page as under `/v2/` | 404 | next to PyPI, for example in an Artifactory virtual index or as a second uv index |

`/v2/` routes each project with its own rule, and sends every other name to PyPI. **To add a project, add a `/v2/<project>/*` rule to the URL map.** Without the rule, `/v2/<project>/` redirects to PyPI, and resolvers install whatever PyPI has under that name. `/astro/` uses one rule that rewrites `/astro/` to `/v2/`, so a new project works there with no change.

The CDN passes the bucket's `Cache-Control` through to clients, so files are cached for a year and pages are not cached. It compresses pages and `.metadata` files with gzip or Brotli for clients that ask for it.

## Requirements

- Python 3.9 or newer, with no packages to install. Run `python3 -m pipindex` from the repository root.
- A Google Cloud SDK with `gcloud storage`, signed in. `python3 -m pipindex` uses the active `gcloud` account; `build-index-page.sh` signs in first with `gsutil-auth-helper.sh`.
- A service account that can create, read and update objects in the bucket. The tool stores custom metadata on existing objects, so it needs `storage.objects.update` as well as create.

## Write a page

After a CI job uploads files to a project folder, write the folder's page:

```bash
./build-index-page.sh pip.astronomer.io v2/<project>
```

The script signs in with `gsutil-auth-helper.sh`, then runs `python3 -m pipindex page`, which inspects each file that has no stored metadata yet.

Never upload a new file under a name the index already has. Locks record each file's hash, so a file that changes breaks every lock that has it. To stop this, the first page write after an upload puts a temporary hold on each dist, and GCS then refuses to overwrite or delete it. To pull a bad file, yank it.

To delete a file, first remove its hold:

```bash
gcloud storage objects update gs://pip.astronomer.io/v2/<project>/<filename> --no-temporary-hold
gcloud storage rm gs://pip.astronomer.io/v2/<project>/<filename>
```

## Yank

To yank a file, set its `yanked` metadata to the reason, then rewrite the page:

```bash
gcloud storage objects update gs://pip.astronomer.io/v2/<project>/<filename> --update-custom-metadata=yanked="<reason>"
./build-index-page.sh pip.astronomer.io v2/<project>
```

To unyank it, use `--remove-custom-metadata=yanked` instead. A yanked file stays downloadable, so existing locks still install it, but new resolves skip it (PEP 592). For a reason with a comma in it, see `gcloud topic escaping`.

## Backfill

To keep the first page write for a large folder from inspecting every old file inside its CI job, run the backfill once before jobs use this version of `build-index-page.sh`:

```bash
python3 -m pipindex backfill pip.astronomer.io v2
```

## Develop

The repo is a uv project for tests and lint. It is not an installable package: CI jobs run `python3 -m pipindex` with no install step, so keep it stdlib-only and working on Python 3.9.

```bash
uv run python -m pipindex --help
uv run python -m unittest discover -s tests
uv run ruff format
uv run ruff check
```

The uv tests lock and sync against a local `http.server`.

To try a page locally:

```bash
mkdir -p /tmp/index/v2/demo && cp dist/* /tmp/index/v2/demo/
uv run python -m pipindex --local page /tmp/index v2/demo
python3 -m http.server -d /tmp/index
uv lock --default-index http://127.0.0.1:8000/v2/
```
