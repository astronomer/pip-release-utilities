#!/usr/bin/env bash

set -euo pipefail

# In our CircleCI jobs we define the credentials JSON in a env var, but gsutil
# won't read them from there; if we have a value for that env then set it up

if [[ -n "${GOOGLE_APPLICATION_CREDENTIALS_CONTENT:-}" ]]; then
  gcloud auth activate-service-account --key-file=<(echo "$GOOGLE_APPLICATION_CREDENTIALS_CONTENT")
  # gs util needs a project set. Default to the one from the included
  # credentials file. (Don't ask me why gsutil doesn't do this itself)
  export CLOUDSDK_CORE_PROJECT="${CLOUDSDK_CORE_PROJECT:-$(
    python3 -c 'import json, os; print(json.loads(os.environ["GOOGLE_APPLICATION_CREDENTIALS_CONTENT"])["project_id"])'
  )}"
fi
