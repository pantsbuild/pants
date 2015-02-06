#!/usr/bin/env bash

set -euo pipefail
IFS=$'\n\t'

expected_header=$(cat <<EOF
# coding=utf-8
# Copyright YYYY Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

EOF
)

py_files=$(find src tests pants-plugins examples -name '*.py' -not -name __init__.py)
known_bad_headers=$(cat <<EOF
tests/python/pants_test/tasks/false.py
tests/python/pants_test/tasks/true.py
EOF
)

bad_files=""
for file in $py_files
do
  if echo "$known_bad_headers" | grep -Fx "$file" >> /dev/null
  then
    #known bad file, skip
    continue
  fi
  header=$(head -7 "$file"|sed -e 's/20[0-9][0-9]/YYYY/' -e 's/	/        /g')
  if [[ "$header" != "$expected_header" ]]
  then
    bad_files="${bad_files}"$'\n'"${file}"
  fi
done

if [[ "x$bad_files" != "x" ]]
then
  echo "ERROR: All .py files other than __init__.py should start with the following header"
  echo "$expected_header"
  echo "---"
  echo "The following files don't:"
  echo "$bad_files"
  exit 1
fi
