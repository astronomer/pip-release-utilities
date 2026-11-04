"""Write the index page of each project folder in a static package index in GCS.

Each project folder, such as v2/apache-airflow, holds the files and an index.html
that pip and uv read (PEP 503). The page gives each file's hash, upload time, size,
Python requirement and yank state. The tool works out those details once per file
and stores them as custom metadata on the file's GCS object ("object metadata"),
so a page rewrite does not download the files again.

Run it with `python3 -m pipindex` from the repository root.
"""
