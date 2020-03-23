# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
from pathlib import Path
from textwrap import dedent

from pex.resolver import resolve

from pants.backend.codegen.thrift.lib.thrift import Thrift
from pants.backend.codegen.thrift.python.apache_thrift_py_gen import ApacheThriftPyGen
from pants.backend.codegen.thrift.python.python_thrift_library import PythonThriftLibrary
from pants.backend.python.interpreter_cache import PythonInterpreterCache
from pants.backend.python.targets.python_library import PythonLibrary
from pants.base.build_environment import get_buildroot
from pants.python.python_repos import PythonRepos
from pants.testutil.subsystem.util import global_subsystem_instance
from pants.testutil.task_test_base import TaskTestBase


class ApacheThriftPyGenTest(TaskTestBase):
    @classmethod
    def task_type(cls):
        return ApacheThriftPyGen

    @staticmethod
    def get_thrift_version(apache_thrift_gen):
        thrift = global_subsystem_instance(Thrift).scoped_instance(apache_thrift_gen)
        return thrift.get_options().version

    def generate_single_thrift_target(self, python_thrift_library):
        context = self.context(target_roots=[python_thrift_library])
        apache_thrift_gen = self.create_task(context)
        apache_thrift_gen.execute()

        def is_synthetic_python_library(target):
            return isinstance(target, PythonLibrary) and target.is_synthetic

        synthetic_targets = context.targets(predicate=is_synthetic_python_library)

        self.assertEqual(1, len(synthetic_targets))
        return apache_thrift_gen, synthetic_targets[0]

    def init_py_path(self, target, package_rel_dir):
        return os.path.join(self.build_root, target.target_base, package_rel_dir, "__init__.py")

    def assert_ns_package(self, target, package_rel_dir):
        with open(self.init_py_path(target, package_rel_dir), "r") as fp:
            self.assertEqual(
                "__import__('pkg_resources').declare_namespace(__name__)", fp.read().strip()
            )

    def assert_leaf_package(self, target, package_rel_dir, *services):
        # We know thrift controls exported package symbols using `__all__`; so reading this out of the
        # `__init__.py` is enough to show we haven't trampled non-trivial thrift-generated `__init__.py`
        # files.

        symbols = {}
        with open(self.init_py_path(target, package_rel_dir), "rb") as fp:
            exec(fp.read(), symbols)

        self.assertIn("__all__", symbols)
        self.assertEqual(sorted(("constants", "ttypes") + services), sorted(symbols["__all__"]))

    def test_single_namespace(self):
        self.create_file(
            "src/thrift/com/foo/one.thrift",
            contents=dedent(
                """
                namespace py foo.bar

                const i32 THINGCONSTANT = 42

                struct Thing {}

                service ThingService {}
                """
            ),
        )
        one = self.make_target(
            spec="src/thrift/com/foo:one", target_type=PythonThriftLibrary, sources=["one.thrift"]
        )
        _, synthetic_target = self.generate_single_thrift_target(one)
        self.assertEqual(
            {
                "foo/__init__.py",
                "foo/bar/__init__.py",
                "foo/bar/ThingService-remote",
                "foo/bar/ThingService.py",
                "foo/bar/ttypes.py",
                "foo/bar/constants.py",
            },
            set(synthetic_target.sources_relative_to_source_root()),
        )
        self.assert_ns_package(synthetic_target, "foo")
        self.assert_leaf_package(synthetic_target, "foo/bar", "ThingService")

    def test_inserts_unicode_header(self):
        """Test that the thrift compiler inserts utf-8 coding header."""
        self.create_file(
            "src/thrift/com/foo/one.thrift",
            contents=dedent(
                """
                namespace py foo.bar
                /**
                 * This comment has a unicode string:	🐈
                 * That is a cat, and it's used for testing purposes.
                 * When this is compiled, the thrift compiler should include the "coding=UTF-8".
                 * at the beginning of the python file.
                 **/
                struct Foo {
                  1: i64 id,
                }(persisted='true')
                """
            ),
        )
        one = self.make_target(
            spec="src/thrift/com/foo:one", target_type=PythonThriftLibrary, sources=["one.thrift"]
        )

        _, synthetic_target = self.generate_single_thrift_target(one)
        for filepath in synthetic_target.sources_relative_to_buildroot():
            if "__init__" not in filepath:
                first_line = Path(get_buildroot(), filepath).read_text().splitlines()[0]
                self.assertEqual(first_line, "# -*- coding: utf-8 -*-")

    def test_nested_namespaces(self):
        self.create_file(
            "src/thrift/com/foo/one.thrift",
            contents=dedent(
                """
                namespace py foo.bar

                struct One {}
                """
            ),
        )
        self.create_file(
            "src/thrift/com/foo/bar/two.thrift",
            contents=dedent(
                """
                namespace py foo.bar.baz

                struct Two {}
                """
            ),
        )
        one = self.make_target(
            spec="src/thrift/com/foo:one",
            target_type=PythonThriftLibrary,
            sources=["one.thrift", "bar/two.thrift"],
        )
        _, synthetic_target = self.generate_single_thrift_target(one)
        self.assertEqual(
            {
                "foo/__init__.py",
                "foo/bar/__init__.py",
                "foo/bar/constants.py",
                "foo/bar/ttypes.py",
                "foo/bar/baz/__init__.py",
                "foo/bar/baz/constants.py",
                "foo/bar/baz/ttypes.py",
            },
            set(synthetic_target.sources_relative_to_source_root()),
        )
        self.assert_ns_package(synthetic_target, "foo")
        self.assert_leaf_package(synthetic_target, "foo/bar")
        self.assert_leaf_package(synthetic_target, "foo/bar/baz")

    def test_namespace_effective(self):
        self.create_file(
            "src/thrift/com/foo/one.thrift",
            contents=dedent(
                """
                namespace py foo.bar

                struct One {}
                """
            ),
        )
        one = self.make_target(
            spec="src/thrift/com/foo:one", target_type=PythonThriftLibrary, sources=["one.thrift"]
        )
        apache_thrift_gen, synthetic_target_one = self.generate_single_thrift_target(one)

        self.create_file(
            "src/thrift2/com/foo/two.thrift",
            contents=dedent(
                """
                namespace py foo.baz

                struct Two {}
                """
            ),
        )
        two = self.make_target(
            spec="src/thrift2/com/foo:two", target_type=PythonThriftLibrary, sources=["two.thrift"]
        )
        _, synthetic_target_two = self.generate_single_thrift_target(two)

        # Confirm separate PYTHONPATH entries, which we need to test namespace packages.
        self.assertNotEqual(synthetic_target_one.target_base, synthetic_target_two.target_base)

        targets = (synthetic_target_one, synthetic_target_two)
        self.context(for_subsystems=[PythonInterpreterCache, PythonRepos])
        interpreter_cache = PythonInterpreterCache.global_instance()
        python_repos = PythonRepos.global_instance()
        interpreter = interpreter_cache.select_interpreter_for_targets(targets)

        # We need setuptools to import namespace packages under python 2 (via pkg_resources), so we
        # prime the PYTHONPATH with a known good version of setuptools.
        # TODO(John Sirois): We really should be emitting setuptools in a
        # `synthetic_target_extra_dependencies` override in `ApacheThriftPyGen`:
        #   https://github.com/pantsbuild/pants/issues/5975
        pythonpath = [os.path.join(get_buildroot(), t.target_base) for t in targets]
        for resolved_dist in resolve(
            [f"thrift=={self.get_thrift_version(apache_thrift_gen)}", "setuptools==40.6.3"],
            interpreter=interpreter,
            indexes=python_repos.indexes,
            find_links=python_repos.repos,
        ):
            pythonpath.append(resolved_dist.distribution.location)

        process = subprocess.Popen(
            [
                interpreter.binary,
                "-c",
                "from foo.bar.ttypes import One; from foo.baz.ttypes import Two",
            ],
            env={"PYTHONPATH": os.pathsep.join(pythonpath)},
            stderr=subprocess.PIPE,
        )
        _, stderr = process.communicate()
        self.assertEqual(0, process.returncode, stderr)

    def test_compatibility_passthrough(self):
        py2_thrift_library = self.make_target(
            spec="src/thrift/com/foo:py2",
            target_type=PythonThriftLibrary,
            sources=[],
            compatibility=["CPython>=2.7,<3"],
        )
        _, py2_synthetic_target = self.generate_single_thrift_target(py2_thrift_library)

        self.assertEqual(py2_thrift_library.compatibility, py2_synthetic_target.compatibility)

        py3_thrift_library = self.make_target(
            spec="src/thrift/com/foo:py3",
            target_type=PythonThriftLibrary,
            sources=[],
            compatibility=["CPython>=3,<3.7"],
        )
        _, py3_synthetic_target = self.generate_single_thrift_target(py3_thrift_library)

        self.assertEqual(py3_thrift_library.compatibility, py3_synthetic_target.compatibility)
        self.assertNotEqual(py3_synthetic_target.compatibility, py2_synthetic_target.compatibility)
