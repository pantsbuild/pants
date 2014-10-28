# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.python.python_requirement import PythonRequirement
from pants.base.payload import Payload
from pants.base.payload_field import PythonRequirementsField
from pants.base.target import Target
from pants.base.validation import assert_list

class PythonRequirementLibrary(Target):
  """Named target for some pip requirements."""
  def __init__(self, payload=None, requirements=None, **kwargs):
    """
    :param requirements: pip requirements
    :type requirements: List of :ref:`python_requirement <bdict_python_requirement>`\s
    """
    payload = payload or Payload()

    assert_list(requirements, expected_type=PythonRequirement)
    payload.add_fields({
      'requirements': PythonRequirementsField(requirements or []),
    })
    super(PythonRequirementLibrary, self).__init__(payload=payload, **kwargs)
