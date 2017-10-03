#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT=$(cd "$(git rev-parse --show-toplevel)" && pwd)

source ${REPO_ROOT}/build-support/common.sh

function _fetch() {
  local readonly url="$1"

  curl -nsSL "${url}"
}

function _json_path() {
  local readonly path="$1"

  python <(cat << EOF
from __future__ import print_function

import json
import sys

json_data = json.load(sys.stdin)
if isinstance(json_data, list):
  if len(json_data) > 1:
    sys.exit(1)
  elif len(json_data) == 1:
    json_data = json_data[0]
  else:
    sys.exit(0)

if not isinstance(json_data, dict):
  sys.exit(1)

for field in "${path}".split('.'):
  json_data = json_data[field]

print(str(json_data))
EOF
)
}

function _allowed_origins() {
  local readonly repo="$1"

  echo "https://github.com/${repo}"
  echo "https://github.com/${repo}.git"
  echo "git@github.com:${repo}.git"
}

function _api_url() {
  local readonly repo="$1"

  echo "https://api.github.com/repos/${repo}"
}

function _find_parent_pr() {
  local readonly repo="$1"
  local readonly pr="$2"

  local readonly pulls_api_url="$(_api_url "${repo}")/pulls"
  local readonly base=$(_fetch "${pulls_api_url}/${pr}" | _json_path "base.label")
  _fetch "${pulls_api_url}?state=open&head=${base}" | _json_path "number"
}

function _apply_pr_patch() {
  local readonly repo="$1"
  local readonly pr="$2"

  local readonly pr_api_url="$(_api_url "${repo}")/pulls/${pr}"
  local readonly pr_data="$(_fetch "${pr_api_url}")"

  local readonly head="$(echo "${pr_data}" | _json_path "head.sha")"
  local readonly status_api_url="$(_api_url "${repo}")/commits/${head}/status"
  local readonly status="$(_fetch "${status_api_url}" | _json_path "state")"
  if [[ "${status}" != success ]]; then
    die "Refusing to apply patch for PR#${pr} since its status is '${status}' and not 'success'."
  fi

  local readonly patch_url="$(echo "${pr_data}" | _json_path "patch_url")"
  local readonly title="$(echo "${pr_data}" | _json_path "title")"
  local readonly description="$(echo "${pr_data}" | _json_path "body")"

  local readonly commit_message=$(cat << EOF
${title}

${description}
EOF
)

  local readonly base="$(git rev-parse HEAD)"

  _fetch "${patch_url}" | git am -k3 >&2
  local readonly tip="$(git rev-parse HEAD)"

  # Re-apply the patch series as a single squash commit retaining authorship info.
  git reset --hard "${base}" >&2
  git merge --squash "${tip}" >&2
  git commit -C "${tip}" >&2

  # Now re-work the commit message to match the PR title/description.
  git commit --amend -m"${commit_message}" >&2
}

function find_origin() {
  local readonly repo="$1"

  for remote in $(git remote); do
    url=$(git remote get-url --all "${remote}")
    for allowed_url in $(_allowed_origins "${repo}"); do
      if [[ "${url}" == "${allowed_url}" ]]; then
        echo "${remote}"
        return
      fi
    done
  done
}

function check_clean_branch() {
  if [[ -n "$(git status --porcelain)" ]]; then
    die "You are not on a clean branch."
  fi
}

function prepare_branch() {
  local readonly origin="$1"
  local readonly pr="$2"
  local readonly branch="_land_/${pr}"

  git fetch "${origin}" master
  git checkout -B "${branch}" "${origin}/master"
  echo "${branch}"
}

function land_pr() {
  local readonly repo="$1"
  local readonly pr="$2"

  local landed=()
  local readonly parent_pr=$(_find_parent_pr "${repo}" "${pr}")
  if [[ -n "${parent_pr}" ]]; then
    echo "Found parent PR#${parent_pr} to land for PR#${pr}" >&2
    landed_parents=(
      $(land_pr "${repo}" "${parent_pr}")
    )
    if (( ${#landed_parents[@]} == 0 )); then
      die "Failed to apply patch for parent PR#${parent_pr}"
    fi
    landed+=(
      ${landed_parents[@]}
    )
  else
    echo "Found no parent PR to land for PR#${pr}" >&2
  fi

  if ! _apply_pr_patch "${repo}" "${pr}"; then
    die "Failed to apply patch for PR#${pr}"
  fi

  landed+=("${pr}")
  echo "${landed[@]}"
}

function push_origin() {
  local readonly origin="$1"

  git push "${origin}" HEAD:master
}

repo="pantsbuild/pants"

function usage() {
  echo "Lands pull requests."
  echo
  echo "Usage: $0 -h"
  echo "Usage: $0 (-n) (-r USER/REPO) PR"
  echo
  echo " -h print out this help message"
  echo " -n perform a dry run; ie: land the PR but do not push to origin"
  echo " -r [github repo in USER/REPO form] (default: ${repo})"
  echo
  echo "This script will find parent PRs that have not been landed and land them"
  echo "as well".

  if (( $# > 0 )); then
    die "$@"
  else
    exit 0
  fi
}

dry_run="false"
while getopts "hnr:" opt; do
  case ${opt} in
    h) usage ;;
    n) dry_run="true" ;;
    r) repo="${OPTARG}" ;;
    *) usage "Invalid option: -${OPTARG}" ;;
  esac
done

readonly PR="${@:$OPTIND:1}"
if [[ -z "${PR}" ]]; then
  usage "A PR is required."
fi

check_clean_branch

readonly repo_origin=$(find_origin "${repo}")
if [[ -z "${repo_origin}" ]]; then
  die "Failed to find a remote configured for ${repo}, please add one."
fi

readonly local_branch=$(prepare_branch "${repo_origin}" "${PR}")
if [[ -z "${local_branch}" ]]; then
  die "Failed to setup a local branch to land PR#${PR} on."
fi

readonly prs=$(land_pr "${repo}" "${PR}")
if [[ -z "${prs[@]}" ]]; then
  die "Failed to land PR#${PR}."
fi

if [[ ${dry_run} == "true" ]]; then
  log "Landed ${prs[@]} on local branch ${local_branch}, not pushing to ${repo_origin}"
else
  push_origin "${repo_origin}"
  log "Landed ${prs[@]} on ${repo_origin}/master"
  git checkout -
fi
