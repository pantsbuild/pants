# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.base.payload import Payload
from pants.base.payload_field import PythonRequirementsField
from pants.base.validation import assert_list
from pants.build_graph.target import Target
from pants.python.python_requirement import PythonRequirement


class PythonRequirementLibrary(Target):
    """A set of pip requirements.

    :API: public
    """

    def __init__(self, payload=None, requirements=None, **kwargs):
        """
        :param requirements: pip requirements as `python_requirement <#python_requirement>`_\\s.
        :type requirements: List of python_requirement calls
        """
        payload = payload or Payload()

        assert_list(requirements, expected_type=PythonRequirement, key_arg="requirements")
        payload.add_fields({"requirements": PythonRequirementsField(requirements or [])})
        super().__init__(payload=payload, **kwargs)

    @property
    def requirements(self):
        return self.payload.requirements
