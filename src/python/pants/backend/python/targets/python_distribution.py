# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.targets.python_target import PythonTarget
from pants.backend.python.targets.python_tests import PythonTests


class PythonDistribution(PythonTarget):
  """A Python distribution containing c/cpp extensions.

  :API: public
  """

  @classmethod
  def alias(cls):
    return 'python_distribution'

  default_sources_globs = '*.(c|cpp|h|py)'


  def __init__(self,
  			       source=None,
               setup_file=None,
               repositories=None,
               platforms=(),
               **kwargs):

  	payload = Payload()
    payload.add_fields({
      'setup_file': PrimitiveField(setup_file),
      'repositories': PrimitiveField(maybe_list(repositories or [])),
      'platforms': PrimitiveField(tuple(maybe_list(platforms or []))),
    })

  	sources = [] if source is None else [source]
    super(PythonDistribution, self).__init__(sources=sources, payload=payload, **kwargs)

    @property
    def setup_file(self):
      return self.payload.setup_file

    @property
    def platforms(self):
      return self.payload.platforms

    @property
    def repositories(self):
      return self.payload.repositories


