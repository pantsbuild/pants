# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.python_requirement import PythonRequirement
from pants.base.payload import Payload
from pants.base.payload_field import PythonRequirementsField
from pants.base.validation import assert_list
from pants.build_graph.target import Target


class PythonRequirementLibrary(Target):
  """Named target for some pip requirements."""

  def __init__(self, payload=None, requirements=None, **kwargs):
    """
    :param requirements: pip requirements as `python_requirement <#python_requirement>`_\s.
    :type requirements: List of python_requirement calls
    """
    payload = payload or Payload()

    assert_list(requirements, expected_type=PythonRequirement, key_arg='requirements')
    payload.add_fields({
      'requirements': PythonRequirementsField(requirements or []),
    })
    super(PythonRequirementLibrary, self).__init__(payload=payload, **kwargs)
    self.add_labels('python')
