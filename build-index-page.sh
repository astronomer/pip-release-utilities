#!/usr/bin/env bash

set -euo pipefail

bucket="${1?Missing bucket name argument}"

"$(dirname "$0")/gsutil-auth-helper.sh"

(
  echo '<!DOCTYPE html><html><head><title>Astronomer Python Packages</title></head><body><pre>'
  gsutil ls -lh "gs://$bucket/simple/" | sed '/\/$\|index.html$/d; s!gs://[^/]\+/simple/\(.*\)$!<a href="\1">\1</a>!'
  echo '</pre></body></html>'
) > index.html

gsutil -h 'Content-Type: text/html' -h "Cache-Control:no-cache,max-age=0" cp -a public-read index.html "gs://$bucket/simple/index.html"
