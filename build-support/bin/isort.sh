#!/usr/bin/env bash

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "${REPO_ROOT}" || exit

# shellcheck source=build-support/common.sh
source build-support/common.sh

function usage() {
  echo "Checks import sort order for python files, optionally fixing incorrect"
  echo "sorts."
  echo
  echo "Usage: $0 (-h|-f)"
  echo " -h    print out this help message"
  echo " -f    instead of erroring on files with bad import sort order, fix"
  echo "       those files"
  if (( $# > 0 )); then
    die "$@"
  else
    exit 0
  fi
}

isort_args=(
  --check-only
)

while getopts "hf" opt
do
  case ${opt} in
    h) usage ;;
    f) isort_args=() ;;
    *) usage "Invalid option: -${OPTARG}" ;;
  esac
done

# If changes were made or issues found, output with leading whitespace trimmed.
output="$(./pants --changed-parent="$(git_merge_base)" fmt.isort -- "${isort_args[@]}")"
echo "${output}" | grep -Eo '(ERROR).*$' && exit 1
echo "${output}" | grep -Eo '(Fixing).*$'
exit 0
