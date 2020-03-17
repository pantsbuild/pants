# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pex.interpreter import PythonInterpreter

from pants.backend.python.tasks.resolve_requirements_task_base import ResolveRequirementsTaskBase
from pants.python.pex_build_util import has_python_requirements, is_python_target


class ResolveRequirements(ResolveRequirementsTaskBase):
    """Resolve external Python requirements."""

    REQUIREMENTS_PEX = "python_requirements_pex"

    options_scope = "resolve-requirements"

    @classmethod
    def product_types(cls):
        return [cls.REQUIREMENTS_PEX]

    @classmethod
    def prepare(cls, options, round_manager):
        round_manager.require_data(PythonInterpreter)

    def execute(self):
        if not self.context.targets(lambda t: is_python_target(t) or has_python_requirements(t)):
            return
        interpreter = self.context.products.get_data(PythonInterpreter)
        pex = self.resolve_requirements(interpreter, self.context.targets(has_python_requirements))
        self.context.products.register_data(self.REQUIREMENTS_PEX, pex)
