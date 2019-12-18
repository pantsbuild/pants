#!/bin/bash -eu

exit_code=0

# NB: we intentionally don't want quote expansion here. See https://github.com/koalaman/shellcheck/wiki/SC2016.
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
  exit_code=1
fi

# Skip release.sh because it has a custom function for failing noisily.
bad_output="$(find ./* -name '*.sh' -not -path './build-support/bin/release.sh' -print0 \
  | xargs -0 grep -H 'curl '| grep -v 'curl --fail' | cut -d: -f1 \
  | grep -v build-support/bin/check_shell.sh \
  || :)"

if [[ -n "${bad_output}" ]]; then
  echo >&2 "Found bash files with curl not followed by --fail."
  echo >&2 "This is bad because 404s and such will end up with error pages in the output files."
  echo >&2 "Matches:"
  echo "${bad_output}"
  exit_code=1
fi

exit "${exit_code}"
