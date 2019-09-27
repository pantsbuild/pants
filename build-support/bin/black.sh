#!/usr/bin/env bash

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "${REPO_ROOT}" || exit 1

# shellcheck source=build-support/common.sh
source build-support/common.sh

function usage() {
  echo "Formats python files with black through pants"
  echo
  echo "Usage: $0 (-h|-f)"
  echo " -h    print out this help message"
  echo " -f    instead of erroring on files with incorrect formatting, fix"
  echo "       those files"
  if (( $# > 0 )); then
    die "$@"
  else
    exit 0
  fi
}

black_args=(
  --check
)

while getopts "hf" opt
do
  case ${opt} in
    h) usage ;;
    f) black_args=() ;;
    *) usage "Invalid option: -${OPTARG}" ;;
  esac
done

./pants --changed-parent="$(git_merge_base)" fmt-v2 --black-options="${black_args[*]}"
