# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.tasks.pex_build_util import has_python_requirements
from pants.backend.python.tasks.resolve_requirements_task_base import ResolveRequirementsTaskBase


class ResolveRequirements(ResolveRequirementsTaskBase):
  """Resolve external Python requirements."""
  REQUIREMENTS_PEX = 'python_requirements_pex'

  @classmethod
  def product_types(cls):
    return [cls.REQUIREMENTS_PEX]

  def execute(self):
    pex = self.resolve_requirements(self.context.targets(has_python_requirements))
    self.context.products.register_data(self.REQUIREMENTS_PEX, pex)
