# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from builtins import str

from twitter.common.collections import maybe_list

from pants.backend.python.targets.python_target import PythonTarget
from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField


class PythonDistribution(PythonTarget):
  """A Python distribution target that accepts a user-defined setup.py."""

  default_sources_globs = '*.py'

  @classmethod
  def alias(cls):
    return 'python_dist'

  def __init__(self,
               address=None,
               payload=None,
               sources=None,
               setup_requires=None,
               **kwargs):
    """
    :param address: The Address that maps to this Target in the BuildGraph.
    :type address: :class:`pants.build_graph.address.Address`
    :param payload: The configuration encapsulated by this target.  Also in charge of most
                    fingerprinting details.
    :type payload: :class:`pants.base.payload.Payload`
    :param sources: Files to "include". Paths are relative to the
      BUILD file's directory.
    :type sources: ``Fileset`` or list of strings. Must include setup.py.
    :param compatibility: either a string or list of strings that represents
      interpreter compatibility for this target, using the Requirement-style
      format, e.g. ``'CPython>=3', or just ['>=2.7','<3']`` for requirements
      agnostic to interpreter class.
    """
    if not 'setup.py' in sources:
      raise TargetDefinitionException(
        self, 'A setup.py in the top-level directory relative to the target definition is required.')

    payload = payload or Payload()
    payload.add_fields({
      'setup_requires': PrimitiveField(maybe_list(setup_requires or ()))
    })
    super(PythonDistribution, self).__init__(
      address=address, payload=payload, sources=sources, **kwargs)

  @property
  def has_native_sources(self):
    return self.has_sources(extension=tuple(self.native_source_extensions))

  @property
  def platforms(self):
    return ['current']

  @property
  def setup_requires(self):
    return self.payload.setup_requires
