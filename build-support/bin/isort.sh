#!/usr/bin/env bash

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd ${REPO_ROOT}

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

# We run differently when in the context of a git hook because otherwise nested .isort.cfg files
# are not found, leading to false negatives. See: https://github.com/timothycrosley/isort#git-hook
# Note that the git_hook only checks tracked files, all of which we wish to isort.  The
# non-GIT_HOOK command line invocation unfortunately must list top-level directories in order to
# avoid python files in virtualenvs created under build-support (Using the single . top-level dir
# finds these files, leading to many false negatives.).
if [[ -n "${GIT_HOOK}" ]]
then
  python << EOF
import sys
from isort.hooks import git_hook


sys.exit(git_hook(strict=True))
EOF
else
  ./pants fmt.isort -- ${isort_args[@]} --recursive src tests pants-plugins contrib examples testprojects
fi

