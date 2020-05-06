# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from contextlib import contextmanager
from typing import Iterator

from pants.fs.fs import safe_filename_from_path
from pants.init.util import init_workdir
from pants.option.option_value_container import OptionValueContainer
from pants.testutil.test_base import TestBase
from pants.util.contextutil import temporary_dir


class UtilTest(TestBase):
    @contextmanager
    def physical_workdir_base(self) -> Iterator[OptionValueContainer]:
        with temporary_dir(cleanup=False) as physical_workdir_base:
            bootstrap_options = self.get_bootstrap_options(
                [f"--pants-physical-workdir-base={physical_workdir_base}"]
            )
            yield bootstrap_options

    def assert_exists(self, path):
        self.assertTrue(os.path.exists(path))

    def assert_symlink(self, path):
        self.assertTrue(os.path.islink(path))

    def physical_workdir(self, bootstrap_options):
        if bootstrap_options.pants_physical_workdir_base:
            return os.path.join(
                bootstrap_options.pants_physical_workdir_base,
                safe_filename_from_path(self.pants_workdir),
            )
        else:
            return self.pants_workdir

    def test_init_workdir(self) -> None:
        with self.physical_workdir_base() as bootstrap_options:
            # Assert pants_workdir exists
            self.assert_exists(self.pants_workdir)

            init_workdir(bootstrap_options)

            # Assert pants_workdir is a symlink after init_workdir above
            self.assert_symlink(self.pants_workdir)
            # Assert symlink target's physical dir exists
            self.assert_exists(os.path.join(self.physical_workdir(bootstrap_options)))
