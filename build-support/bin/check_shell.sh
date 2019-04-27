#!/bin/bash -eu

# shellcheck disable=SC2016
bad_output="$(find ./* -name '*.sh' -print0 \
  | xargs -0 grep '^ *\(readonly\|declare\) .*\(\$(\|`\)' \
  || :)"

if [[ -n "${bad_output}" ]]; then
  echo >&2 "Found bash files with readonly variables defined by invoking subprocesses."
  echo >&2 "This is bad because \`set -e\` doesn't exit if these fail."
  echo >&2 "Make your variable non-readonly, or define it and then mark it readonly."
  echo >&2 "Matches:"
  echo "${bad_output}"
  exit 1
fi
