# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)


from twitter.common.collections import maybe_list

from pants.backend.python.targets.python_target import PythonTarget
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField

class PythonDistribution(PythonTarget):
  """A Python distribution.

  """

  @classmethod
  def alias(cls):
    return 'python_distribution'


  def __init__(self, **kwargs):
    payload = Payload()
    super(PythonDistribution, self).__init__(sources=[], payload=payload, **kwargs)
