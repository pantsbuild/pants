# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import shutil
import uuid
from contextlib import contextmanager

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest
from pants.util.contextutil import environment_as, temporary_dir
from pants.util.dirutil import safe_walk


class PantsRequirementIntegrationTestBase(PantsRunIntegrationTest):
    @contextmanager
    def _unstable_pants_version(self):
        # The earliest pantsbuild.pants release on pypi is 0.0.17 so we grab a lower version and tack
        # on a globally unique local version identifier to ensure we can never collide with past,
        # present or future stable or unstable releases.
        unstable_version = f"0.0.0+{uuid.uuid4().hex}"

        # Notes must be configured for all pants versions so we fake that out ephemerally here.
        # In pants-plugins/src/python/internal_backend/utilities/register.py see
        # PantsReleases.notes_for_version.
        with environment_as(
            _PANTS_VERSION_OVERRIDE=unstable_version,
            PANTS_PANTS_RELEASES_BRANCH_NOTES="{'0.0.x': 'pants.toml'}",
        ):
            pants_run = self.run_pants(["--version"])
            self.assert_success(pants_run)
            self.assertEqual(unstable_version, pants_run.stdout_data.strip())
            yield

    def _iter_wheels(self, path):
        for root, _, files in safe_walk(path):
            for f in files:
                if f.endswith(".whl"):
                    yield os.path.join(root, f)

    @contextmanager
    def create_unstable_pants_distribution(self):
        with self._unstable_pants_version():
            with temporary_dir() as dist_dir:
                create_pants_dist_cmd = [
                    f"--pants-distdir={dist_dir}",
                    "setup-py",
                    "--run=bdist_wheel",
                    "src/python/pants:pants-packaged",
                ]
                pants_run = self.run_pants(create_pants_dist_cmd)
                self.assert_success(pants_run)

                # Create a flat wheel repo from the results of setup-py above.
                with temporary_dir() as repo:
                    for wheel in self._iter_wheels(dist_dir):
                        shutil.copy(wheel, os.path.join(repo, os.path.basename(wheel)))

                    yield repo
