# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from .nailgun_task_test_base import NailgunTaskTestBase


class JarTaskTestBase(NailgunTaskTestBase):
  """Prepares an ephemeral test build root that supports jar tasks."""
