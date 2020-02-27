#!/usr/bin/env bash

# shellcheck source=build-support/common.sh
source build-support/common.sh

set -euo pipefail

MERGE_BASE="$1"

LINT_OUTPUT_FILE='.lint-output'

trap 'rm -f "$LINT_OUTPUT_FILE"' EXIT

./pants --changed-parent="${MERGE_BASE}" lint2 \
        2>&1 \
  | sed -E -e 's#^would reformat .*/process-execution[a-zA-Z0-9]+/(.*)$#would reformat \1#g' \
  | tee /dev/stderr \
  | sed -E -n -e 's#^would reformat (.*)$#\1#gp' \
  | sort -u \
  | tr '\n' ' ' | sed -E -e 's#(.*) #\1#g' > "$LINT_OUTPUT_FILE" \
  || die "To fix formatting, run:\n\n./pants fmt2 $(cat "$LINT_OUTPUT_FILE")"
