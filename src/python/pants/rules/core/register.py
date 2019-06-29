# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.rules.core import filedeps, list_targets, test


def rules():
  return list_targets.rules() + filedeps.rules() + test.rules()
