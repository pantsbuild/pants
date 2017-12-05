#!/bin/bash -eu

REPO_ROOT="$(cd $(dirname "${BASH_SOURCE[0]}") && cd ../.. && pwd -P)"

buildifier=( "$("${REPO_ROOT}/build-support/bin/download_binary.sh" buildifier foo buildifier)" "-tables=${REPO_ROOT}/build-support/buildifier/tables.json" )

bad_files=( $(find * -name BUILD -or -name 'BUILD.*' | xargs "${buildifier[@]}" -mode=check | awk '{print $1}') )

if [[ "${#bad_files[@]}" -gt 0 ]]; then
  echo >&2 "Some BUILD files were incorrectly formatted."
  echo >&2 "To fix, run \`"${buildifier[@]}" -mode=fix "${bad_files[@]}"\`"
  exit 1
fi
