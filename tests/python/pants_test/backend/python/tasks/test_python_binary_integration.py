# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import glob
import os
import subprocess
from contextlib import contextmanager
from textwrap import dedent

import pytest
from pex.pex_info import PexInfo

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest
from pants.util.collections import assert_single_element
from pants.util.contextutil import open_zip, temporary_dir

_LINUX_PLATFORM = "linux-x86_64-cp-36-m"
_LINUX_WHEEL_SUBSTRING = "manylinux"
_OSX_PLATFORM = "macosx-10.13-x86_64-cp-36-m"
_OSX_WHEEL_SUBSTRING = "macosx"


@pytest.mark.skip(reason="times out")
class PythonBinaryIntegrationTest(PantsRunIntegrationTest):
    @classmethod
    def use_pantsd_env_var(cls):
        """TODO(#7320): See the point about watchman."""
        return False

    @staticmethod
    @contextmanager
    def caching_config():
        """Creates a temporary directory and returns a pants configuration for passing to
        pants_run."""
        with temporary_dir() as tmp_dir:
            yield {
                "cache": {
                    "read": True,
                    "write": True,
                    "read_from": [tmp_dir],
                    "write_to": [tmp_dir],
                }
            }

    def assert_pex_attribute(self, pex, attr, value):
        self.assertTrue(os.path.exists(pex))
        pex_info = PexInfo.from_pex(pex)
        self.assertEqual(getattr(pex_info, attr), value)

    def test_zipsafe_caching(self):
        test_project = "testprojects/src/python/cache_fields"
        test_build = os.path.join(test_project, "BUILD")
        test_src = os.path.join(test_project, "main.py")
        test_pex = "dist/cache_fields.pex"
        zipsafe_target_tmpl = "python_binary(sources=['main.py'], zip_safe={})"

        with self.caching_config() as config, self.temporary_workdir() as workdir, self.temporary_file_content(
            test_src, b""
        ):
            build = lambda: self.run_pants_with_workdir(
                command=["binary", test_project], config=config, workdir=workdir
            )

            # Create a pex from a simple python_binary target and assert it has zip_safe=True (default).
            with self.temporary_file_content(test_build, b"python_binary(sources=['main.py'])"):
                self.assert_success(build())
                self.assert_pex_attribute(test_pex, "zip_safe", True)

            # Simulate a user edit by adding zip_safe=False to the target and check the resulting pex.
            with self.temporary_file_content(
                test_build, zipsafe_target_tmpl.format("False").encode()
            ):
                self.assert_success(build())
                self.assert_pex_attribute(test_pex, "zip_safe", False)

            # Simulate a user edit by adding zip_safe=True to the target and check the resulting pex.
            with self.temporary_file_content(
                test_build, zipsafe_target_tmpl.format("True").encode()
            ):
                self.assert_success(build())
                self.assert_pex_attribute(test_pex, "zip_safe", True)

    def test_platform_defaults_to_config(self):
        self.platforms_test_impl(
            target_platforms=None,
            config_platforms=[_OSX_PLATFORM],
            want_present_platforms=[_OSX_WHEEL_SUBSTRING],
            want_missing_platforms=[_LINUX_PLATFORM],
        )

    def test_target_platform_without_config(self):
        self.platforms_test_impl(
            target_platforms=[_LINUX_PLATFORM],
            config_platforms=None,
            want_present_platforms=[_LINUX_WHEEL_SUBSTRING],
            want_missing_platforms=[_OSX_WHEEL_SUBSTRING],
        )

    def test_target_platform_overrides_config(self):
        self.platforms_test_impl(
            target_platforms=[_LINUX_PLATFORM],
            config_platforms=[_OSX_PLATFORM],
            want_present_platforms=[_LINUX_WHEEL_SUBSTRING],
            want_missing_platforms=[_OSX_WHEEL_SUBSTRING],
        )

    def test_target_platform_narrows_config(self):
        self.platforms_test_impl(
            target_platforms=[_LINUX_PLATFORM],
            config_platforms=[_LINUX_PLATFORM, _OSX_PLATFORM],
            want_present_platforms=[_LINUX_WHEEL_SUBSTRING],
            want_missing_platforms=[_OSX_WHEEL_SUBSTRING],
        )

    def test_target_platform_expands_config(self):
        self.platforms_test_impl(
            target_platforms=[_LINUX_PLATFORM, _OSX_PLATFORM],
            config_platforms=[_LINUX_PLATFORM],
            want_present_platforms=[_LINUX_WHEEL_SUBSTRING, _OSX_WHEEL_SUBSTRING],
        )

    def platforms_test_impl(
        self, target_platforms, config_platforms, want_present_platforms, want_missing_platforms=(),
    ):
        def p537_deps(deps):
            return [d for d in deps if "p537" in d]

        def assertInAny(substring, collection):
            self.assertTrue(
                any(substring in d for d in collection),
                f'Expected an entry matching "{substring}" in {collection}',
            )

        def assertNotInAny(substring, collection):
            self.assertTrue(
                all(substring not in d for d in collection),
                f'Expected no entries matching "{substring}" in {collection}',
            )

        test_project = "testprojects/src/python/cache_fields"
        test_build = os.path.join(test_project, "BUILD")
        test_src = os.path.join(test_project, "main.py")
        test_pex = "dist/cache_fields.pex"

        with self.caching_config() as config, self.temporary_file_content(test_src, b""):
            config["python-setup"] = {"platforms": []}

            build_content = dedent(
                """
                    python_binary(
                      sources=['main.py'],
                      dependencies=[':numpy'],
                      {target_platforms}
                    )
                    python_requirement_library(
                      name='numpy',
                      requirements=[
                        python_requirement('p537==1.0.4')
                      ]
                    )

                    """.format(
                    target_platforms="platforms = [{}],".format(
                        ", ".join(["'{}'".format(p) for p in target_platforms])
                    )
                    if target_platforms is not None
                    else "",
                )
            )
            with self.temporary_file_content(test_build, build_content.encode()):
                # When only the linux platform is requested,
                # only linux wheels should end up in the pex.
                if config_platforms is not None:
                    config["python-setup"]["platforms"] = config_platforms
                result = self.run_pants(
                    command=["binary", test_project], config=config, tee_output=True,
                )
                self.assert_success(result)

            with open_zip(test_pex) as z:
                deps = p537_deps(z.namelist())
                for platform in want_present_platforms:
                    assertInAny(platform, deps)
                for platform in want_missing_platforms:
                    assertNotInAny(platform, deps)

    def test_platforms_with_native_deps(self):
        result = self.run_pants(
            [
                "binary",
                "testprojects/src/python/python_distribution/ctypes:bin",
                "testprojects/src/python/python_distribution/ctypes:with_platforms",
            ]
        )
        self.assert_failure(result)
        self.assertIn(
            dedent(
                """\
                Pants doesn't currently support cross-compiling native code.
                The following targets set platforms arguments other than ['current'], which is unsupported for this reason.
                Please either remove the platforms argument from these targets, or set them to exactly ['current'].
                Bad targets:
                testprojects/src/python/python_distribution/ctypes:with_platforms
                """
            ),
            result.stderr_data,
        )
        self.assertNotIn(
            "testprojects/src/python/python_distribution/ctypes:bin", result.stderr_data
        )

    def test_generate_ipex_tensorflow(self):
        with temporary_dir() as tmp_distdir:
            with self.pants_results(
                [
                    f"--pants-distdir={tmp_distdir}",
                    # tensorflow==1.14.0 has a setuptools>=41.0.0 requirement, so the .ipex resolve fails
                    # without this override.
                    "--pex-builder-wrapper-setuptools-version=41.0.0",
                    "--binary-py-generate-ipex",
                    "binary",
                    "examples/src/python/example/tensorflow_custom_op:show-tf-version",
                ]
            ) as pants_run:
                self.assert_success(pants_run)
                output_ipex = assert_single_element(glob.glob(os.path.join(tmp_distdir, "*")))
                ipex_basename = os.path.basename(output_ipex)
                self.assertEqual(ipex_basename, "show-tf-version.ipex")

                pex_execution_output = subprocess.check_output([output_ipex])
                assert "tf version: 1.14.0" in pex_execution_output.decode()
