# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
from textwrap import dedent

from colors import blue

from pants.backend.python.tasks.gather_sources import GatherSources
from pants.backend.python.tasks.python_binary_create import PythonBinaryCreate
from pants.backend.python.tasks.select_interpreter import SelectInterpreter
from pants.base.run_info import RunInfo
from pants.build_graph.register import build_file_aliases as register_core
from pants_test.backend.python.tasks.python_task_test_base import PythonTaskTestBase


class PythonBinaryCreateTest(PythonTaskTestBase):
    @classmethod
    def task_type(cls):
        return PythonBinaryCreate

    @classmethod
    def alias_groups(cls):
        return super().alias_groups().merge(register_core())

    def _assert_pex(self, binary, expected_output=None, expected_shebang=None):
        # The easiest way to create products required by the PythonBinaryCreate task is to
        # execute the relevant tasks.
        si_task_type = self.synthesize_task_subtype(SelectInterpreter, "si_scope")
        gs_task_type = self.synthesize_task_subtype(GatherSources, "gs_scope")

        task_context = self.context(
            for_task_types=[si_task_type, gs_task_type], target_roots=[binary]
        )
        run_info_dir = os.path.join(self.pants_workdir, self.options_scope, "test/info")
        task_context.run_tracker.run_info = RunInfo(run_info_dir)

        si_task_type(task_context, os.path.join(self.pants_workdir, "si")).execute()
        gs_task_type(task_context, os.path.join(self.pants_workdir, "gs")).execute()

        test_task = self.create_task(task_context)
        test_task.execute()

        self._check_products(
            test_task,
            task_context,
            binary,
            expected_output=expected_output,
            expected_shebang=expected_shebang,
        )

    def _check_products(
        self, test_task, context, binary, expected_output=None, expected_shebang=None
    ):
        pex_name = test_task._get_output_pex_filename(binary.address.target_name)
        products = context.products.get("deployable_archives")
        self.assertIsNotNone(products)
        product_data = products.get(binary)
        product_basedir = list(product_data.keys())[0]
        self.assertEqual(product_data[product_basedir], [pex_name])

        # Check pex copy.
        pex_copy = os.path.join(self.build_root, "dist", pex_name)
        self.assertTrue(os.path.isfile(pex_copy))

        # Check that the pex runs.
        output = subprocess.check_output(pex_copy).decode()
        if expected_output:
            self.assertEqual(expected_output, output)

        # Check that the pex has the expected shebang.
        if expected_shebang:
            with open(pex_copy, "rb") as pex:
                line = pex.readline()
                self.assertEqual(expected_shebang, line)

    def test_deployable_archive_products_simple(self):
        self.create_python_library(
            "src/python/lib",
            "lib",
            {
                "lib.py": dedent(
                    """
        import os


        def main():
            os.getcwd()
        """
                )
            },
        )

        binary = self.create_python_binary(
            "src/python/bin", "bin", "lib.lib:main", dependencies=["src/python/lib"]
        )
        self._assert_pex(binary)

    def test_deployable_archive_products_files_deps(self):
        self.create_library(
            path="src/things", target_type="files", name="things", sources=["loose_file"]
        )
        self.create_file("src/things/loose_file", "data!")
        self.create_python_library(
            "src/python/lib",
            "lib",
            {
                "lib.py": dedent(
                    """
        import io
        import os
        import sys


        def main():
            here = os.path.dirname(__file__)
            loose_file = os.path.join(here, '../src/things/loose_file')
            with io.open(os.path.realpath(loose_file), 'r') as fp:
                sys.stdout.write(fp.read())
        """
                )
            },
        )

        binary = self.create_python_binary(
            "src/python/bin", "bin", "lib.lib:main", dependencies=["src/python/lib", "src/things"]
        )
        self._assert_pex(binary, expected_output="data!")

    def test_shebang_modified(self):
        self.create_python_library(
            "src/python/lib",
            "lib",
            {
                "lib.py": dedent(
                    """
        def main():
            print('Hello World!')
        """
                )
            },
        )

        binary = self.create_python_binary(
            "src/python/bin",
            "bin",
            "lib.lib:main",
            shebang="/usr/bin/env python2",
            dependencies=["src/python/lib"],
        )

        self._assert_pex(
            binary, expected_output="Hello World!\n", expected_shebang=b"#!/usr/bin/env python2\n"
        )

    def test_generate_ipex_ansicolors(self):
        self.create_python_requirement_library(
            "3rdparty/ipex", "ansicolors", requirements=["ansicolors"]
        )
        self.create_python_library(
            "src/ipex",
            "lib",
            {
                "main.py": dedent(
                    """\
        from colors import blue

        print(blue('i just lazy-loaded the ansicolors dependency!'))
        """
                )
            },
        )
        binary = self.create_python_binary(
            "src/ipex", "bin", "main", dependencies=["3rdparty/ipex:ansicolors", ":lib"]
        )

        self.set_options(generate_ipex=True)
        dist_dir = os.path.join(self.build_root, "dist")

        self._assert_pex(
            binary, expected_output=blue("i just lazy-loaded the ansicolors dependency!") + "\n"
        )

        dehydrated_ipex_file = os.path.join(dist_dir, "bin.ipex")
        assert os.path.isfile(dehydrated_ipex_file)
        hydrated_pex_output_file = os.path.join(dist_dir, "bin.pex")
        assert os.path.isfile(hydrated_pex_output_file)
