# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.rules.core import filedeps, list_roots, list_targets, test


def rules():
  return list_roots.rules() + list_targets.rules() + filedeps.rules() + test.rules()
