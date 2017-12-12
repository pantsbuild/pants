# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from twitter.common.collections import maybe_list

from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.build_graph.target import Target

class PythonDistribution(Target):
  """A Python distribution.

  """

  default_sources_globs = '*.py'

  @classmethod
  def alias(cls):
    return 'python_dist'

  def __init__(self,
               address=None,
               payload=None,
               sources=None,
               compatibility=None,
               **kwargs):
    """
    :param dependencies: The addresses of targets that this target depends on.
      These dependencies may
      be ``python_library``-like targets (``python_library``,
      ``python_thrift_library``, ``python_antlr_library`` and so forth) or
      ``python_requirement_library`` targets.
    :type dependencies: list of strings
    :param sources: Files to "include". Paths are relative to the
      BUILD file's directory.
    :type sources: ``Fileset`` or list of strings
    :param resource_targets: The addresses of ``resources`` targets this target
      depends on.
    :param compatibility: either a string or list of strings that represents
      interpreter compatibility for this target, using the Requirement-style
      format, e.g. ``'CPython>=3', or just ['>=2.7','<3']`` for requirements
      agnostic to interpreter class.
    """
    self.address = address
    payload = payload or Payload()
    payload.add_fields({
      'sources': self.create_sources_field(sources, address.spec_path, key_arg='sources'),
      'compatibility': PrimitiveField(maybe_list(compatibility or ()))
    })
    super(PythonDistribution, self).__init__(address=address, payload=payload, **kwargs)
    self.add_labels('python')

    sources_basenames = [os.path.basename(source) for source in sources]
    if not 'setup.py' in sources_basenames:
      raise TargetDefinitionException(self,
        'A setup.py is required to create a python_dist. You must include a setup.py file in your sources field.')

    # Check that the compatibility requirements are well-formed.
    for req in self.payload.compatibility:
      try:
        PythonIdentity.parse_requirement(req)
      except ValueError as e:
        raise TargetDefinitionException(self, str(e))
