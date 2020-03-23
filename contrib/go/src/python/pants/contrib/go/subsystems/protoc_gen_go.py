# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os

from pants.backend.codegen.protobuf.subsystems.protoc import Protoc
from pants.base.workunit import WorkUnitLabel
from pants.scm.git import Git
from pants.subsystem.subsystem import Subsystem, SubsystemError
from pants.util.dirutil import safe_mkdir
from pants.util.memo import memoized_method

from pants.contrib.go.subsystems.go_distribution import GoDistribution

logger = logging.getLogger(__name__)


class ProtocGenGo(Subsystem):
    """A compiled protobuf plugin that generates Go code.

    For details, see https://github.com/golang/protobuf
    """

    options_scope = "protoc-gen-go"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--version",
            default="v1.1.0",
            help="Version of protoc-gen-go plugin to use when generating code",
        )

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (Protoc.scoped(cls), GoDistribution,)

    @memoized_method
    def select(self, context):
        self.get_options()
        workdir = os.path.join(
            self.get_options().pants_workdir,
            self.options_scope,
            "versions",
            self.get_options().version,
        )
        tool_path = os.path.join(workdir, "bin/protoc-gen-go")

        if not os.path.exists(tool_path):
            safe_mkdir(workdir, clean=True)

            # Checkout the git repo at a given version. `go get` always gets master.
            repo = Git.clone(
                "https://github.com/golang/protobuf.git",
                os.path.join(workdir, "src/github.com/golang/protobuf"),
            )
            repo.set_state(self.get_options().version)

            go = GoDistribution.global_instance()
            result, go_cmd = go.execute_go_cmd(
                cmd="install",
                gopath=workdir,
                args=["github.com/golang/protobuf/protoc-gen-go"],
                workunit_factory=context.new_workunit,
                workunit_labels=[WorkUnitLabel.BOOTSTRAP],
            )

            if result != 0:
                raise SubsystemError(f"{go_cmd} failed with exit code {result}")

        logger.info(f"Selected {self.options_scope} binary bootstrapped to: {tool_path}")
        return tool_path
