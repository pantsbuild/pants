# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)


from pex.pex_info import PexInfo
from six import string_types
from twitter.common.collections import maybe_list

from pants.backend.python.targets.python_target import PythonTarget
from pants.backend.python.targets.python_tests import PythonTests
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField

class PythonDistribution(PythonTarget):
  """A Python distribution containing c/cpp extensions.

  :API: public
  """

  @classmethod
  def alias(cls):
    return 'python_distribution'


  def __init__(self,
               platforms=(),
               **kwargs):
    payload = Payload()
    payload.add_fields({
      'platforms': PrimitiveField(tuple(maybe_list(platforms or [])))
    })
    super(PythonDistribution, self).__init__(sources=[], payload=payload, **kwargs)

    @property
    def platforms(self):
      return self.payload.platforms
