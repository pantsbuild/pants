#!/usr/bin/env bash
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

HERE=$(cd `dirname "${BASH_SOURCE[0]}"` && pwd)

# We have special developer mode requirements - namely bs4 and PyYAML
export PANTS_DEV=1

source ${HERE}/../pants_venv

(
  activate_pants_venv && \
  py.test build-support/bin/test_docsitegen.py
)

