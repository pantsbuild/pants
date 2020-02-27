# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.python_artifact import PythonArtifact
from pants.backend.python.targets.python_binary import PythonBinary
from pants.build_graph.address import Address
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.legacy.graph import HydratedTarget
from pants.engine.selectors import Params
from pants.python.python_requirement import PythonRequirement
from pants.testutil.subsystem.util import init_subsystem
from pants.testutil.test_base import TestBase


class PythonTestBase(TestBase):
    @classmethod
    def alias_groups(cls) -> BuildFileAliases:
        return BuildFileAliases(
            objects={"python_requirement": PythonRequirement, "setup_py": PythonArtifact,}
        )

    def tgt(self, addr: str) -> HydratedTarget:
        return self.request_single_product(HydratedTarget, Params(Address.parse(addr)))

    def setUp(self):
        super().setUp()
        init_subsystem(PythonBinary.Defaults)
