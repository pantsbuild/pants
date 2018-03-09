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
 -y           Continue publishing without prompting (prompting for what??? dumb)
 -l  <dir>    Also publish the documentation into the existing local directory <dir>.
 -d  <dir>    publish the site to a subdir staging/<dir> (useful for public
              previews)

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

while getopts "hopyd:" opt; do
  case ${opt} in
    h) usage ;;
    o) preview="true" ;;
    p) publish="true" ;;
    y) publish_confirmed="true" ;;
    d) publish_path="staging/${OPTARG}" ;;
    *) usage "Invalid option: -${OPTARG}" ;;
  esac
done

# TODO(benjy): Instead of invoking Pants multiple times, these actions should be chained using
# products, like everything else.

set -x

${PANTS_EXE} sitegen --pants-config-files=pants.publish.ini \
             src:: examples:: contrib::  \
             testprojects/src/java/org/pantsbuild/testproject/page:readme

${PANTS_EXE} reference \
  --pants-reference-template=reference/pants_reference_body.html \
  --build-dictionary-template=reference/build_dictionary_body.html \
  || die "Failed to generate the reference and/or build dictionary documents."

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

# generate html from markdown pages.
${PANTS_EXE} markdown --fragment \
  src:: examples:: contrib::  \
  testprojects/src/java/org/pantsbuild/testproject/page:readme || \
    die "Failed to generate HTML from markdown'."


# invoke doc site generator.
${PANTS_EXE} sitegen --config-path=src/docs/docsite.json || \
  die "Failed to generate doc site'."

set +x

do_open "${REPO_ROOT}/dist/docsite/index.html"

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
