#!/usr/bin/env bash
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

REPO_ROOT=$(cd $(dirname "${BASH_SOURCE[0]}") && cd "$(git rev-parse --show-toplevel)" && pwd)

source ${REPO_ROOT}/build-support/common.sh

PANTS_EXE="${REPO_ROOT}/pants"

function usage() {
  echo "Publishes the http://pantsbuild.github.io/ docs locally or remotely."
  echo
  echo "Usage: $0 (-h|-opd)"
  echo " -h           print out this help message"
  echo " -o           open the doc site locally"
  echo " -p           publish the doc site remotely"
  echo " -y           continue publishing without prompting"
  echo " -d  <dir>    publish the site to a subdir staging/<dir> (useful for public previews)"

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

${PANTS_EXE} builddict --omit-impl-re='internal_backend.*' || \
  die "Failed to generate the 'BUILD Dictionary' and/or 'Options Reference'."

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
  src:: examples:: src/docs:: //:readme \
  testprojects/src/java/org/pantsbuild/testproject/page:readme || \
    die "Failed to generate HTML from markdown'."

# invoke doc site generator.
${PANTS_EXE} sitegen --config-path=src/python/pants/docs/docsite.json || \
  die "Failed to generate doc site'."

do_open "${REPO_ROOT}/dist/docsite/index.html"

if [[ "${publish}" = "true" ]]; then
  url="http://pantsbuild.github.io/${publish_path}"
  if [[ "${publish_confirmed}" != "true" ]] ; then
    read -ep "To abort publishing these docs to ${url} press CTRL-C, otherwise press enter to \
continue."
  fi
  (
    ${REPO_ROOT}/src/python/pants/docs/publish_via_git.sh \
      git@github.com:pantsbuild/pantsbuild.github.io.git \
      ${publish_path} && \
    do_open ${url}/index.html
  ) || die "Publish to ${url} failed."
fi

