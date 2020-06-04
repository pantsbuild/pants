# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import pathlib
import stat
from contextlib import contextmanager

from pex.pex_builder import PEXBuilder

from pants.backend.python.targets.python_library import PythonLibrary
from pants.python.pex_build_util import PexBuilderWrapper
from pants.source.source_root import SourceRootConfig
from pants.testutil.subsystem.util import init_subsystem
from pants.testutil.test_base import TestBase
from pants.util.contextutil import open_zip, temporary_dir, temporary_file_path


class TestPexBuilderWrapper(TestBase):
    @staticmethod
    def assert_perms(perms, path):
        mode = path.stat().st_mode
        assert perms == stat.S_IMODE(mode)

    @classmethod
    def assert_dir_perms(cls, path):
        cls.assert_perms(0o755, path)

    @classmethod
    def assert_file_perms(cls, path):
        cls.assert_perms(0o644, path)

    @staticmethod
    def pex_builder_wrapper(**kwargs):
        init_subsystem(PexBuilderWrapper.Factory)
        return PexBuilderWrapper.Factory.create(PEXBuilder(**kwargs))

    @staticmethod
    @contextmanager
    def extracted_pex(pex):
        with temporary_dir() as chroot, open_zip(pex) as zip:
            prior_umask = os.umask(0o022)
            try:
                zip.extractall(path=chroot)
            finally:
                os.umask(prior_umask)
            yield pathlib.Path(chroot)

    def test(self):
        init_subsystem(SourceRootConfig, {"source": {"root_patterns": ["src/python"]}})
        self.create_file("src/python/package/module.py")
        implicit_package_target = self.make_target(
            spec="src/python/package", target_type=PythonLibrary, sources=["module.py"]
        )

        pbw = self.pex_builder_wrapper()
        pbw.add_sources_from(implicit_package_target)
        with temporary_file_path() as pex:
            pbw.build(pex)
            with self.extracted_pex(pex) as chroot_path:
                # Check the paths we know about:
                package_path = chroot_path / "package"
                self.assert_dir_perms(package_path)

                user_files = {package_path / f for f in ("__init__.py", "module.py")}
                for user_file in user_files:
                    self.assert_file_perms(user_file)

                # And all other paths pex generates (__main__.py, PEX-INFO, .deps/, etc...):
                for root, dirs, files in os.walk(chroot_path):
                    for d in dirs:
                        dir_path = pathlib.Path(root) / d
                        if dir_path != package_path:
                            self.assert_dir_perms(dir_path)
                    for f in files:
                        file_path = pathlib.Path(root) / f
                        if file_path not in user_files:
                            self.assert_file_perms(file_path)
