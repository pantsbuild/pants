# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import TYPE_CHECKING, List, Optional

from pex.pex import PEX
from pex.pex_builder import PEXBuilder
from pex.pex_info import PexInfo

from pants.python.pex_build_util import PexBuilderWrapper
from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import is_executable, safe_concurrent_creation

if TYPE_CHECKING:
    from pants.python.python_requirement import PythonRequirement  # noqa


class ExecutablePexTool(Subsystem):

    entry_point: Optional[str] = None

    base_requirements: List["PythonRequirement"] = []

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (PexBuilderWrapper.Factory,)

    def bootstrap(
        self, interpreter, pex_file_path, extra_reqs: Optional[List["PythonRequirement"]] = None
    ) -> PEX:
        # Caching is done just by checking if the file at the specified path is already executable.
        if not is_executable(pex_file_path):
            pex_info = PexInfo.default(interpreter=interpreter)
            if self.entry_point is not None:
                pex_info.entry_point = self.entry_point

            with safe_concurrent_creation(pex_file_path) as safe_path:
                all_reqs = list(self.base_requirements) + list(extra_reqs or [])
                pex_builder = PexBuilderWrapper.Factory.create(
                    builder=PEXBuilder(interpreter=interpreter, pex_info=pex_info)
                )
                pex_builder.add_resolved_requirements(all_reqs, platforms=["current"])
                pex_builder.build(safe_path)

        return PEX(pex_file_path, interpreter)
