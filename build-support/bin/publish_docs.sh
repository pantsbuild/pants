#!/usr/bin/env bash
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

set -eo pipefail

PANTS_GH_PAGES='https://github.com/pantsbuild/pantsbuild.github.io.git'
GIT_URL="${GIT_URL:-$PANTS_GH_PAGES}"

REPO_ROOT=$(cd $(dirname "${BASH_SOURCE[0]}") && cd "$(git rev-parse --show-toplevel)" && pwd)

source ${REPO_ROOT}/build-support/common.sh

PANTS_EXE="${REPO_ROOT}/pants"

function usage() {
  cat <<EOF
Generates the Pants html documentation and optionally publishes it locally
and/or remotely.

Usage: $0 (-h|-opyld)
 -h           Print out this help message.
 -p           Publish the site to \$GIT_URL with an automated commit.
 -o           Open the published site in a web browser.
 -y           Continue publishing without a y/n prompt.
 -l  <dir>    Also publish the documentation into the existing local directory <dir>.
 -d  <dir>    publish the site to a subdir staging/<dir> (useful for public
              previews).

Environment Variables and Defaults:
GIT_URL=$PANTS_GH_PAGES
  URL of a git remote repository to publish to with an automated commit.
VIEW_PUBLISH_URL=
EOF

  if (( $# > 0 )); then
    die "$@"
  else
    exit 0
  fi
}

publish_path=""

while getopts "hopyl:d:" opt; do
  case ${opt} in
    h) usage ;;
    o) preview="true" ;;
    p) publish="true" ;;
    y) publish_confirmed="true" ;;
    l) local_dir="${OPTARG}" ;;
    d) publish_path="staging/${OPTARG}" ;;
    *) usage "Invalid option: -${OPTARG}" ;;
  esac
done

set -x

${PANTS_EXE} --pants-config-files=pants.publish.ini \
             sitegen --config-path='src/docs/docsite.json' \
             src:: examples:: contrib::  \
             testprojects/src/java/org/pantsbuild/testproject/page:readme \
  || die "Failed to generate doc site'."

function do_open() {
  if [[ "${preview}" = "true" ]]; then
    if which xdg-open &>/dev/null; then
      xdg-open $1
    elif which open &>/dev/null; then
      open $1
    else
      die "Failed to find an opener on your system for $1"
    fi
  fi
}

set +x

if [[ -z "$local_dir" ]]; then
  do_open "${REPO_ROOT}/dist/docsite/index.html"
else
  find "${REPO_ROOT}/dist/docsite" -mindepth 1 -maxdepth 1 \
    | xargs -I '{}' cp -r '{}' "$local_dir"
  do_open "${local_dir}/index.html"
fi

if [[ "${publish}" = "true" ]]; then
  url="http://pantsbuild.github.io/${publish_path}"
  if [[ "${publish_confirmed}" != "true" ]] ; then
    read -ep "To abort publishing these docs to ${url} press CTRL-C, otherwise press enter to \
continue."
  fi
  (
    ${REPO_ROOT}/src/docs/publish_via_git.sh \
      $GIT_URL \
      ${publish_path}
    do_open ${url}/index.html
  ) || die "Publish to ${url} failed."
fi

# Note that we use Cloudflare to enforce:
#
# - Flattening the apex domain pantsbuild.org to www.pantsbuild.org
# - Requiring HTTPS
# - Directing www.pantsbuild.org traffic via CNAME to pantsbuild.github.io.
# - Caching www.pantsbuild.org content.
# - Directing binaries.pantsbuild.org and node-preinstalled-modules.pantsbuild.org
#   to the appropriate S3 buckets via CNAME.

# Google domains is still our registrar, but we use it only to point to Cloudflare's nameservers.

# See the DNS and Page Rules tabs in our Cloudflare acct, and also the GitHub Pages
# custom domain setup here:  https://github.com/pantsbuild/pantsbuild.github.io/settings
