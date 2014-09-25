#!/usr/bin/env bash
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

REPO_ROOT=$(cd $(dirname "${BASH_SOURCE[0]}") && cd "$(git rev-parse --show-toplevel)" && pwd)

# We have special developer mode requirements - namely sphinx deps.
export PANTS_DEV=1

source ${REPO_ROOT}/build-support/pants_venv

function usage() {
  echo "Publishes the http://pantsbuild.github.io/ docs locally or remotely."
  echo
  echo "Usage: $0 (-h|-opd)"
  echo " -h           print out this help message"
  echo " -o           open the doc site locally"
  echo " -p           publish the doc site remotely"
  echo " -d           publish the site to a subdir at this path (useful for public previews)"

  if (( $# > 0 )); then
    die "$@"
  else
    exit 0
  fi
}

publish_path=""

while getopts "hopd:" opt; do
  case ${opt} in
    h) usage ;;
    o) preview="true" ;;
    p) publish="true" ;;
    d) publish_path="${OPTARG}" ;;
    *) usage "Invalid option: -${OPTARG}" ;;
  esac
done

${REPO_ROOT}/pants goal builddict --print-exception-stacktrace || \
  die "Failed to generate the 'BUILD Dictionary'."
cp dist/builddict/*.rst src/python/pants/docs/

(
  activate_pants_venv && \
  cd src/python/pants/docs && \
  make clean html
) || die "Failed to generate the doc tree."

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

do_open "${REPO_ROOT}/src/python/pants/docs/_build/html/index.html"

if [[ "${publish}" = "true" ]]; then
  url="http://pantsbuild.github.io/${publish_path}"
  read -ep "To abort publishing these docs to ${url} press CTRL-C, otherwise press enter to \
continue."
  (
    ${REPO_ROOT}/src/python/pants/docs/publish_via_git.sh \
      git@github.com:pantsbuild/pantsbuild.github.io.git \
      ${publish_path} && \
    do_open ${url}/index.html
  ) || die "Publish to ${url} failed."
fi

