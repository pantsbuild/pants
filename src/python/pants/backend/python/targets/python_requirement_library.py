# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.base.build_manual import manual
from pants.base.target import Target
from pants.base.payload import PythonRequirementLibraryPayload


@manual.builddict(tags=["python"])
class PythonRequirementLibrary(Target):
  def __init__(self, requirements=None, *args, **kwargs):
    payload = PythonRequirementLibraryPayload(requirements)
    super(PythonRequirementLibrary, self).__init__(*args, payload=payload, **kwargs)
