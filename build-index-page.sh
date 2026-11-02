#!/usr/bin/env bash

set -euo pipefail

bucket="${1?Missing bucket name argument}"
folder="${2-simple}"

"$(dirname "$0")/gsutil-auth-helper.sh"

cd "$(dirname "$0")"
exec python3 -m pipindex page "$bucket" "$folder"
