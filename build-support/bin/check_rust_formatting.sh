#!/usr/bin/env bash

REPO_ROOT="$(git rev-parse --show-toplevel)"

function usage() {
  echo "Checks formatting of rust files, optionally fixing mis-formatted files."
  echo
  echo "Usage: $0 (-h|-f)"
  echo " -h    print out this help message"
  echo " -f    instead of erroring on files with bad formatting, fix those files"

  if [[ -n "$*" ]]; then
    echo
    echo "$@"
  fi
}

check="true"

while getopts "hf" opt; do
  case ${opt} in
    h)
      usage
      exit 0
      ;;
    f)
      check="false"
      ;;
    *)
      usage "Unrecognized arguments."
      exit 1
      ;;
  esac
done

cmd=(
  "${REPO_ROOT}/cargo" fmt --all --
)
if [[ "${check}" == "true" ]]; then
  cmd=("${cmd[@]}" "--check")
fi

# WONTFIX: fixing the array expansion is too difficult to be worth it. See https://github.com/koalaman/shellcheck/wiki/SC2207.
# shellcheck disable=SC2207
bad_files=(
  $(
    # Ensure generated code is present since `cargo fmt` needs to do enough parsing to follow use's
    # and these will land in generated code.
    echo >&2 "Ensuring generated code is present for downstream formatting checks..."
    "${REPO_ROOT}/cargo" check -p bazel_protos

    "${cmd[@]}" | \
      awk '$0 ~ /^Diff in/ {print $3}' | \
      sort -u
    exit "${PIPESTATUS[0]}"
  )
)
exit_code=$?

if [[ ${exit_code} -ne 0 ]]; then
  if [[ "${check}" == "true" ]]; then
    echo >&2 "The following Rust files were incorrectly formatted, run \`$0 -f\` to reformat them:"
    for bad_file in ${bad_files[*]}; do
      echo >&2 "${bad_file}"
    done
  else
    cat << EOF >&2
An error occurred while checking the formatting of Rust files:
EOF
    cd "${NATIVE_ROOT}" && "${cmd[@]}" >/dev/null
  fi
  exit 1
fi
