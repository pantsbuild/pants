#!/usr/bin/env bash

set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd ${REPO_ROOT}

# Read added files from stdin, and ensure check_header_helper.py checks for the current copyright
# year for the intersection of these files with the ones it checks.
# Check for copies (-C) and moves (-M), so we don't get false positives when people do
# refactorings. -l50 bounds the time git takes to search for these non-additions.
# See git-diff(1) and https://stackoverflow.com/a/2299672/2518889 for discussion of these options.
# Exporting IGNORE_ADDED_FILES will avoid checking the specific copyright year for added files.
git diff --cached --name-only --diff-filter=A -C -M -l50 \
  | build-support/bin/check_header_helper.py src tests pants-plugins examples contrib
