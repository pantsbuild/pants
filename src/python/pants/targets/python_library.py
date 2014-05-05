# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.base.build_manual import manual
from pants.targets.python_target import PythonTarget


@manual.builddict(tags=["python"])
class PythonLibrary(PythonTarget):
  """Produces a Python library."""
  pass
