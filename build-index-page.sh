#!/usr/bin/env bash

set -euo pipefail

bucket="${1?Missing bucket name argument}"
folder="${2-simple}"

# Strip any trailing slashes
bucket="${bucket%/}"
folder="${folder%/}"

"$(dirname "$0")/gsutil-auth-helper.sh"

while [[ -n "$folder" ]]; do
  pip install requirements.txt
  python generate_index_html.py $bucket $folder> index.html

  gsutil -h 'Content-Type: text/html' -h "Cache-Control:no-cache,max-age=0" cp -a public-read index.html "gs://$bucket/$folder/index.html"

  next_folder="${folder%/*}"
  if [[ $folder == $next_folder ]]; then
    break;
  else
    folder="$next_folder"
  fi
done
