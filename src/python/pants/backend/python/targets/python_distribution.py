# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import ast
import os
import re

from pex.interpreter import PythonIdentity
from twitter.common.collections import maybe_list

from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.build_graph.target import Target


class PythonDistribution(Target):
  """A Python distribution target that accepts a user-defined setup.py."""

  default_sources_globs = '*.py'

  @classmethod
  def alias(cls):
    return 'python_dist'

  @staticmethod
  def get_setup_py_install_requires(setup_file_path):
    with open(setup_file_path) as fp:
      file_content = fp.read()
      matches = re.findall(r'install_requires=\[.*\]', file_content)
      ret = []
      if matches:
        ret = ast.literal_eval('[' + matches[-1].split('[')[1])
      return ret

  def __init__(self,
               address=None,
               payload=None,
               sources=None,
               compatibility=None,
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
    payload = payload or Payload()
    payload.add_fields({
      'sources': self.create_sources_field(sources, address.spec_path, key_arg='sources'),
      'compatibility': PrimitiveField(maybe_list(compatibility or ()))
    })
    super(PythonDistribution, self).__init__(address=address, payload=payload, **kwargs)
    self.add_labels('python')

    setup_file_path = None
    for path in self.sources_relative_to_buildroot():
      if os.path.basename(path) == 'setup.py':
        setup_file_path = path

    self.install_requires = self.get_setup_py_install_requires(setup_file_path)

    if not setup_file_path:
      raise TargetDefinitionException(
        self, 'A setup.py in the top-level directory relative to the target definition is required.'
      )

    # Check that the compatibility requirements are well-formed.
    for req in self.payload.compatibility:
      try:
        PythonIdentity.parse_requirement(req)
      except ValueError as e:
        raise TargetDefinitionException(self, str(e))
