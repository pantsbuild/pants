# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.python_requirement import PythonRequirement
from pants.base.payload import Payload
from pants.base.payload_field import PythonRequirementsField
from pants.base.target import Target
from pants.base.validation import assert_list


class PythonRequirementLibrary(Target):
  """Named target for some pip requirements."""
  def __init__(self, address=None, payload=None, requirements=None, **kwargs):
    """
    :param requirements: pip requirements as `python_requirement <#python_requirement>`_\s.
    :type requirements: List of python_requirement calls
    """
    payload = payload or Payload()

    # A 'private' constructor parameter - `requirements_relpath` - is used by the
    # `python_requirements` macro to associate a requirements text file with each
    # PythonRequirementLibrary it expands to.
    requirements_relpath = kwargs.pop('requirements_relpath', None)
    if requirements_relpath:
      sources_field = self.create_sources_field(sources=[requirements_relpath],
                                                sources_rel_path=address.spec_path,
                                                key_arg='sources')
      payload.add_field('sources', sources_field)

    assert_list(requirements, expected_type=PythonRequirement, key_arg='requirements')
    payload.add_field('requirements', PythonRequirementsField(requirements or []))
    super(PythonRequirementLibrary, self).__init__(address=address, payload=payload, **kwargs)
    self.add_labels('python')
