#!/usr/bin/env bash

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT" || exit 1

# shellcheck source=build-support/common.sh
source "${REPO_ROOT}/build-support/common.sh"

function usage() {
  echo "Generates contributor lists."
  echo
  echo "Usage: $0 (-h|-s revision)"
  echo " -h           print out this help message"
  echo " -s           generate the contribution roster since the given revision"
  echo
  echo "By default, CONTRIBUTORS.md is re-generated to account for any new"
  echo "since the last re-generation."
  echo
  echo "If \`-s [revision]\` is specified, then the contribution roster since that"
  echo "revision is output.  This is useful to generate a thank-you list for"
  echo "release announcements by specifying \`-s [previous release tag]\`."

  if (( $# > 0 )); then
    die "$@"
  else
    exit 0
  fi
}

since=""

while getopts "hs:" opt; do
  case ${opt} in
    h) usage ;;
    s) since="${OPTARG}" ;;
    *) usage "Invalid option: -${OPTARG}" ;;
  esac
done

function contributors() {
  range="${1:-HEAD}"

  # Include all commits in range but exclude:
  #  - all commits from the imported zinc tree.
  #  - commits that are from running the publish goal
  git log --use-mailmap --format="format:%aN;%s" "${range}" ^imported_zinc_tree \
    | grep -v "pants build committing publish data" \
    | sed -e 's/;.*$//'

}

if [[ -n "${since}" ]]; then
  contributors "${since}..HEAD" | sort | uniq -c | sort -rn
else
  cat << HEADER > CONTRIBUTORS.md
Created by running \`$0\`.

HEADER

  (cat - - <(contributors) << FIXED_LIST
# You can add contributors that don't show up as an author in the git log
# manually here.  Just add a line for their full name.  Comments and blank
# lines are ignored.

# Contributor from Square shepherded by Eric.
Alyssa Pohahau

FIXED_LIST
) | grep -v -E "^[[:space:]]*#" | \
    grep -v -E "^[[:space:]]*$" | \
    LC_ALL=C sort -u | \
    sed -E -e "s|^|+ |" >> CONTRIBUTORS.md
fi
