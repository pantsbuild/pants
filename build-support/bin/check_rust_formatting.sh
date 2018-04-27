#!/usr/bin/env bash

REPO_ROOT="$(git rev-parse --show-toplevel)"
source "${REPO_ROOT}/build-support/bin/native/bootstrap.sh"

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

ensure_native_build_prerequisites >/dev/null

cmd=(
  "${CARGO_HOME}/bin/rustfmt"
  --config-path="${NATIVE_ROOT}/rustfmt.toml"
)

files=(
  $(find "${NATIVE_ROOT}" \
      -name '*.rs' -not -wholename '*/bazel_protos/*' -not -wholename '*/target/*')
  "${NATIVE_ROOT}/process_execution/bazel_protos/src/verification.rs"
  "${NATIVE_ROOT}/process_execution/bazel_protos/build.rs"
)

bad_files=(
  $(
    ${cmd[*]} --write-mode=${write_mode} ${files[*]} 2>/dev/null | \
      awk '$0 ~ /^Diff in/ {print $3}' | \
      sort -u
     exit ${PIPESTATUS[0]}
  )
)
case $? in
  4)
    echo >&2 "The following rust files were incorrectly formatted, run \`$0 -f\` to reformat them:"
    for bad_file in ${bad_files[*]}; do
      echo >&2 ${bad_file}
    done
    exit 1
    ;;
  0)
    exit 0
    ;;
  *)
    cat << EOF >&2
An error occurred while checking the formatting of rust files.
Try running \`${cmd[*]} --write-mode=diff ${files[*]}\` to investigate.
Its error is:
EOF
    ${cmd[*]} --write-mode=diff ${files[*]} >/dev/null
    exit 1
    ;;
esac
