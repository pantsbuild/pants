#!/usr/bin/env bash

REPO_ROOT="$(git rev-parse --show-toplevel)"

function usage() {
  echo "Checks formatting of rust files, optionally fixing mis-formatted files."
  echo
  echo "Usage: $0 (-h|-f)"
  echo " -h    print out this help message"
  echo " -f    instead of erroring on files with bad formatting, fix those files"

  if [[ -n "$@" ]]; then
    echo
    echo "$@"
  fi
}

write_mode=diff

while getopts "hf" opt; do
  case ${opt} in
    h)
      usage
      exit 0
      ;;
    f)
      write_mode=overwrite
      ;;
    *)
      usage "Unrecognized arguments."
      exit 1
      ;;
  esac
done

NATIVE_ROOT="${REPO_ROOT}/src/rust/engine"

cmd=(
  ${REPO_ROOT}/build-support/bin/native/cargo fmt --all --
)

bad_files=(
  $(
    if [[ -z "${CHECK_RUST_FORMATTING_DEBUG}" ]]; then
      exec 2>/dev/null
    fi
    cd "${NATIVE_ROOT}"
    ${cmd[*]} --write-mode=${write_mode} | \
      awk '$0 ~ /^Diff in/ {print $3}' | \
      sort -u
    exit ${PIPESTATUS[0]}
  )
)
case $? in
  2)
    # NB: This will happen when running rustfmt against a clean repo where generated modules that
    # are referenced by checked in code will not exist yet (rustfmt does not execute the build).
    # This is also fine since any real syntax errors will be caught by compile checks!
    echo >&2 "NB: Skipped formatting some files due to syntax errors."
    if [[ -z "${CHECK_RUST_FORMATTING_DEBUG}" ]]; then
    echo >&2 "To see the errors, run:"
    echo >&2 "CHECK_RUST_FORMATTING_DEBUG=1 $0"
    echo >&2
    fi
    ;& # Fallthrough
  4)
    if (( ${#bad_files[@]} > 0 )); then
      echo >&2 "The following rust files were incorrectly formatted, run \`$0 -f\` to reformat them:"
      for bad_file in ${bad_files[*]}; do
        echo >&2 ${bad_file}
      done
      exit 1
    fi
    ;;
  0)
    exit 0
    ;;
  *)
    cat << EOF >&2
An error occurred while checking the formatting of rust files.
Try running \`(cd "${NATIVE_ROOT}" && ${cmd[*]} --write-mode=diff)\` to investigate.
Its error is:
EOF
    cd "${NATIVE_ROOT}" && ${cmd[*]} --write-mode=diff >/dev/null
    exit 1
    ;;
esac
