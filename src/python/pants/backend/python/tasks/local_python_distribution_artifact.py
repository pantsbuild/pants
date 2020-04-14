# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.base.build_environment import get_buildroot
from pants.python.pex_build_util import is_local_python_dist
from pants.task.task import Task
from pants.util.dirutil import safe_mkdir
from pants.util.fileutil import atomic_copy


class LocalPythonDistributionArtifact(Task):
    @classmethod
    def prepare(cls, options, round_manager):
        super().prepare(options, round_manager)
        round_manager.require_data("local_wheels")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.dist_dir = self.get_options().pants_distdir

    def execute(self):
        dist_targets = self.context.targets(is_local_python_dist)

        local_wheels_product = self.context.products.get("local_wheels")
        if not local_wheels_product:
            return
        safe_mkdir(self.dist_dir)  # Make sure dist dir is present.
        for t in dist_targets:
            # Copy generated wheel files to dist folder
            target_local_wheels = local_wheels_product.get(t)
            if not target_local_wheels:
                continue
            for output_dir, base_names in target_local_wheels.items():
                for base_name in base_names:
                    wheel_output = os.path.join(output_dir, base_name)
                    self.context.log.debug(f"found local built wheels {wheel_output}")
                    # Create a copy for wheel in dist dir.
                    wheel_copy = os.path.join(self.dist_dir, base_name)
                    atomic_copy(wheel_output, wheel_copy)
                    self.context.log.info(
                        "created wheel {}".format(os.path.relpath(wheel_copy, get_buildroot()))
                    )
