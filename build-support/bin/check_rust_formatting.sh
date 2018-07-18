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

write_mode=check

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
    cd "${NATIVE_ROOT}"

    # Ensure generated code is present since `cargo fmt` needs to do enough parsing to follow use's
    # and these will land in generated code.
    echo >&2 "Ensuring generated code is present for downstream formatting checks..."
    ${REPO_ROOT}/build-support/bin/native/cargo check -p bazel_protos

    ${cmd[*]} --write-mode=${write_mode} | \
      awk '$0 ~ /^Diff in/ {print $3}' | \
      sort -u
    exit ${PIPESTATUS[0]}
  )
)
exit_code=$?

if [[ ${exit_code} -ne 0 ]]; then
  if [[ "${write_mode}" == "check" ]]; then
    echo >&2 "The following rust files were incorrectly formatted, run \`$0 -f\` to reformat them:"
    for bad_file in ${bad_files[*]}; do
      echo >&2 ${bad_file}
    done
  else
    cat << EOF >&2
An error occurred while checking the formatting of rust files.
Try running \`(cd "${NATIVE_ROOT}" && ${cmd[*]} --write-mode=${write_mode})\` to investigate.
Its error is:
EOF
    cd "${NATIVE_ROOT}" && ${cmd[*]} --write-mode=${write_mode} >/dev/null
  fi
  exit 1
fi
