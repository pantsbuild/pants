#!/usr/bin/env bash

REPO_ROOT="$(cd $(dirname "${BASH_SOURCE[0]}") && cd ../.. && pwd -P)"
source "${REPO_ROOT}/build-support/bin/native/bootstrap.sh"

ensure_native_build_prerequisites >/dev/null

files=( $(find "${NATIVE_ROOT}" -name '*.rs' -not -wholename '*/bazel_protos/*' -not -wholename '*/target/*') )
cmd=( "${CARGO_HOME}/bin/rustfmt" --config-path="${NATIVE_ROOT}/rustfmt.toml" )

bad_files=( $(${cmd[*]} ${files[*]} --write-mode=diff 2>/dev/null | awk '$0 ~ /^Diff in/ {print $3}' | sort -u ; exit ${PIPESTATUS[0]}) )
case $? in
  4)
    echo >&2 "Some rust files were incorrectly formatted. Run \`${cmd[*]} --write-mode=overwrite ${bad_files[*]}\` to reformat them."
    exit 1
    ;;
  0)
    exit 0
    ;;
  *)
    echo >&2 "An error occured while checking the formatting of rust files. Try running \`${cmd[*]} --write-mode=diff ${files[*]}\` to investigate."
    exit 1
    ;;
esac
