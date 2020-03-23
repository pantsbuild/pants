# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import shutil

from pants.base.build_environment import get_buildroot
from pants.util.dirutil import safe_mkdir
from pants.util.memo import memoized_property

from pants.contrib.go.tasks.go_task import GoTask


class GoBinaryCreate(GoTask):
    """Creates self contained go executables."""

    @classmethod
    def prepare(cls, options, round_manager):
        super().prepare(options, round_manager)
        round_manager.require_data("exec_binary")

    @memoized_property
    def dist_root(self):
        # TODO(John Sirois): impose discipline on dist/ output by tasks - they should all be
        # namespacing with a top-level `dist/` dir of their own.
        return os.path.join(self.get_options().pants_distdir, "go", "bin")

    def execute(self):
        binaries = self.context.targets(self.is_binary)
        if not binaries:
            return

        # TODO(John Sirois): Consider adding invalidation support; although, copying a binary is
        # very fast.
        executable_by_binary = self.context.products.get_data("exec_binary")
        safe_mkdir(self.dist_root)
        rel_dist_root = os.path.relpath(self.dist_root, get_buildroot())
        for binary in binaries:
            executable = executable_by_binary[binary]
            shutil.copy(executable, os.path.join(self.dist_root))
            self.context.log.info(
                "creating {}".format(os.path.join(rel_dist_root, os.path.basename(executable)))
            )
