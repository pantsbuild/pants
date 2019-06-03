#!/usr/bin/env bash

# TODO: This is in a separate file so it can be tested in isolation in test_git_hooks.py. This can and
# should all be moved to python code.

# Check for copies (-C) and moves (-M), so we don't get false positives when people do
# refactorings. -l50 bounds the time git takes to search for these non-additions.
# See git-diff(1) and https://stackoverflow.com/a/2299672/2518889 for discussion of these options.
exec git --no-pager diff --cached --name-only --diff-filter=A -C -M -l50
