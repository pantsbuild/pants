# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from collections import OrderedDict
from contextlib import contextmanager
from textwrap import dedent
from unittest.mock import Mock

from twitter.common.dirutil.chroot import Chroot

from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.tasks.select_interpreter import SelectInterpreter
from pants.backend.python.tasks.setup_py import SetupPy, declares_namespace_package
from pants.base.exceptions import TaskError
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.prep_command import PrepCommand
from pants.build_graph.resources import Resources
from pants.build_graph.target import Target
from pants.fs.archive import TGZ
from pants.testutil.interpreter_selection_utils import skip_unless_python36_present
from pants.testutil.subsystem.util import init_subsystem
from pants.util.contextutil import temporary_dir, temporary_file
from pants.util.dirutil import safe_mkdir
from pants.util.ordered_set import OrderedSet
from pants_test.backend.python.tasks.python_task_test_base import PythonTaskTestBase


class SetupPyTestBase(PythonTaskTestBase):
    @classmethod
    def task_type(cls):
        return SetupPy

    def setUp(self):
        super().setUp()
        self.distdir = os.path.join(self.build_root, "dist")
        self.set_options(pants_distdir=self.distdir)
        init_subsystem(Target.Arguments)

    def prepare_setup_py(self, target, recursive=False):
        self.set_options(recursive=recursive)
        si_task_type = self.synthesize_task_subtype(SelectInterpreter, "si_scope")
        context = self.context(for_task_types=[si_task_type], target_roots=[target])
        si_task_type(context, os.path.join(self.pants_workdir, "si")).execute()
        return self.create_task(context)

    @contextmanager
    def run_execute(self, target, recursive=False):
        setup_py = self.prepare_setup_py(target, recursive=recursive)
        setup_py.execute()
        yield setup_py.context.products.get_data(SetupPy.PYTHON_DISTS_PRODUCT)


class TestSetupPy(SetupPyTestBase):
    def setUp(self):
        super().setUp()
        self.dependency_calculator = SetupPy.DependencyCalculator(self.build_graph)

    @classmethod
    def alias_groups(cls):
        extra_aliases = BuildFileAliases(
            targets={"prep_command": PrepCommand, "resources": Resources, "target": Target}
        )
        return super().alias_groups().merge(extra_aliases)

    def create_dependencies(self, depmap):
        target_map = {}
        for name, deps in depmap.items():
            target_map[name] = self.create_python_library(
                relpath=name, name=name, provides=f'setup_py(name="{name}", version="0.0.0")'
            )
        for name, deps in depmap.items():
            target = target_map[name]
            dep_targets = [target_map[name] for name in deps]
            for dep in dep_targets:
                self.build_graph.inject_dependency(target.address, dep.address)
        return target_map

    def assert_requirements(self, target, expected):
        reduced_dependencies = self.dependency_calculator.reduced_dependencies(target)
        self.assertEqual(SetupPy.install_requires(reduced_dependencies), expected)

    def test_reduced_dependencies_1(self):
        # foo -> bar -> baz
        dep_map = OrderedDict(foo=["bar"], bar=["baz"], baz=[])
        target_map = self.create_dependencies(dep_map)
        self.assertEqual(
            self.dependency_calculator.reduced_dependencies(target_map["foo"]),
            OrderedSet([target_map["bar"]]),
        )
        self.assertEqual(
            self.dependency_calculator.reduced_dependencies(target_map["bar"]),
            OrderedSet([target_map["baz"]]),
        )
        self.assertEqual(
            self.dependency_calculator.reduced_dependencies(target_map["baz"]), OrderedSet()
        )
        self.assert_requirements(target_map["foo"], OrderedSet(["bar==0.0.0"]))
        self.assert_requirements(target_map["bar"], OrderedSet(["baz==0.0.0"]))
        self.assert_requirements(target_map["baz"], OrderedSet())

    def test_execution_reduced_dependencies_1(self):
        dep_map = OrderedDict(foo=["bar"], bar=["baz"], baz=[])
        target_map = self.create_dependencies(dep_map)
        with self.run_execute(target_map["foo"], recursive=False) as created:
            self.assertEqual([target_map["foo"]], list(created.keys()))
        with self.run_execute(target_map["foo"], recursive=True) as created:
            self.assertEqual(
                {target_map["baz"], target_map["bar"], target_map["foo"]}, set(created.keys())
            )

    def test_reduced_dependencies_2(self):
        # foo --> baz
        #  |      ^
        #  v      |
        # bar ----'
        dep_map = OrderedDict(foo=["bar", "baz"], bar=["baz"], baz=[])
        target_map = self.create_dependencies(dep_map)
        self.assertEqual(
            self.dependency_calculator.reduced_dependencies(target_map["foo"]),
            OrderedSet([target_map["bar"], target_map["baz"]]),
        )
        self.assertEqual(
            self.dependency_calculator.reduced_dependencies(target_map["bar"]),
            OrderedSet([target_map["baz"]]),
        )
        self.assertEqual(
            self.dependency_calculator.reduced_dependencies(target_map["baz"]), OrderedSet()
        )

    def test_reduced_dependencies_diamond(self):
        #   bar <-- foo --> baz
        #    |               |
        #    `----> bak <----'
        dep_map = OrderedDict(foo=["bar", "baz"], bar=["bak"], baz=["bak"], bak=[])
        target_map = self.create_dependencies(dep_map)
        self.assertEqual(
            self.dependency_calculator.reduced_dependencies(target_map["foo"]),
            OrderedSet([target_map["bar"], target_map["baz"]]),
        )
        self.assertEqual(
            self.dependency_calculator.reduced_dependencies(target_map["bar"]),
            OrderedSet([target_map["bak"]]),
        )
        self.assertEqual(
            self.dependency_calculator.reduced_dependencies(target_map["baz"]),
            OrderedSet([target_map["bak"]]),
        )
        self.assert_requirements(target_map["foo"], OrderedSet(["bar==0.0.0", "baz==0.0.0"]))
        self.assert_requirements(target_map["bar"], OrderedSet(["bak==0.0.0"]))
        self.assert_requirements(target_map["baz"], OrderedSet(["bak==0.0.0"]))

    def test_binary_target_injected_into_reduced_dependencies(self):
        foo_bin_dep = self.create_python_library(relpath="foo/dep", name="dep")

        foo_bin = self.create_python_binary(
            relpath="foo/bin", name="bin", entry_point="foo.bin:foo", dependencies=["foo/dep"]
        )

        foo = self.create_python_library(
            relpath="foo",
            name="foo",
            provides=dedent(
                """
                setup_py(
                    name='foo',
                    version='0.0.0'
                ).with_binaries(
                    foo_binary='foo/bin'
                )
                """
            ),
        )

        self.assertEqual(
            self.dependency_calculator.reduced_dependencies(foo), OrderedSet([foo_bin, foo_bin_dep])
        )
        entry_points = dict(SetupPy.iter_entry_points(foo))
        self.assertEqual(entry_points, {"foo_binary": "foo.bin:foo"})

        with self.run_execute(foo, recursive=False) as created:
            self.assertEqual([foo], list(created.keys()))

        with self.run_execute(foo, recursive=True) as created:
            self.assertEqual([foo], list(created.keys()))

    def test_binary_target_injected_into_reduced_dependencies_with_provider(self):
        bar_bin_dep = self.create_python_library(
            relpath="bar/dep",
            name="dep",
            provides=dedent(
                """
                setup_py(
                    name='bar_bin_dep',
                    version='0.0.0'
                )
                """
            ),
        )

        bar_bin = self.create_python_binary(
            relpath="bar/bin", name="bin", entry_point="bar.bin:bar", dependencies=["bar/dep"],
        )

        bar = self.create_python_library(
            relpath="bar",
            name="bar",
            provides=dedent(
                """
                setup_py(
                  name='bar',
                  version='0.0.0'
                ).with_binaries(
                  bar_binary='bar/bin'
                )
                """
            ),
        )

        self.assertEqual(
            self.dependency_calculator.reduced_dependencies(bar), OrderedSet([bar_bin, bar_bin_dep])
        )
        self.assert_requirements(bar, OrderedSet(["bar_bin_dep==0.0.0"]))
        entry_points = dict(SetupPy.iter_entry_points(bar))
        self.assertEqual(entry_points, {"bar_binary": "bar.bin:bar"})

        with self.run_execute(bar, recursive=False) as created:
            self.assertEqual([bar], list(created.keys()))

        with self.run_execute(bar, recursive=True) as created:
            self.assertEqual({bar_bin_dep, bar}, set(created.keys()))

    def test_pants_contrib_case(self):
        def create_requirement_lib(name):
            return self.create_python_requirement_library(
                relpath=name, name=name, requirements=[f"{name}==1.1.1"]
            )

        req1 = create_requirement_lib("req1")
        create_requirement_lib("req2")
        req3 = create_requirement_lib("req3")

        self.create_python_library(
            relpath="src/python/pants/base", name="base", dependencies=["req1", "req2"]
        )
        self.create_python_binary(
            relpath="src/python/pants/bin",
            name="bin",
            entry_point="pants.bin.pants_loader:main",
            dependencies=[
                # Should be stripped in reduced_dependencies since pants_packaged provides these sources.
                "src/python/pants/base",
            ],
        )
        pants_packaged = self.create_python_library(
            relpath="src/python/pants",
            name="pants_packaged",
            provides=dedent(
                """
                setup_py(
                  name='pants_packaged',
                  version='0.0.0'
                ).with_binaries(
                  # Should be stripped in reduced_dependencies since pants_packaged provides this.
                  pants_bin='src/python/pants/bin'
                )
                """
            ),
        )
        contrib_lib = self.create_python_library(
            relpath="contrib/lib/src/python/pants/contrib/lib",
            name="lib",
            dependencies=[
                "req3",
                # Should be stripped in reduced_dependencies since pants_packaged provides these sources.
                "src/python/pants/base",
            ],
        )
        contrib_plugin = self.create_python_library(
            relpath="contrib/lib/src/python/pants/contrib",
            name="plugin",
            provides=dedent(
                """
                setup_py(
                  name='contrib',
                  version='0.0.0'
                )
                """
            ),
            dependencies=[
                "contrib/lib/src/python/pants/contrib/lib",
                "src/python/pants:pants_packaged",
                "req1",
            ],
        )
        reduced_dependencies = self.dependency_calculator.reduced_dependencies(contrib_plugin)
        self.assertEqual(
            reduced_dependencies, OrderedSet([contrib_lib, req3, pants_packaged, req1])
        )

    def test_no_exported(self):
        foo = self.create_python_library(relpath="foo", name="foo")
        with self.run_execute(foo):
            pass

    def test_no_owner(self):
        self.create_python_library(relpath="foo", name="foo")
        exported = self.create_python_library(
            relpath="bar",
            name="bar",
            dependencies=["foo"],
            provides=dedent(
                """
                setup_py(
                  name='bar',
                  version='0.0.0'
                )
                """
            ),
        )
        # `foo` is not in `bar`'s address space and has no owner in its own address space.
        with self.assertRaises(self.dependency_calculator.NoOwnerError):
            self.dependency_calculator.reduced_dependencies(exported)

    def test_ambiguous_owner(self):
        self.create_python_library(relpath="foo/bar", name="bar")
        self.add_to_build_file(
            "foo",
            dedent(
                """
                python_library(
                  name='foo1',
                  sources=[],
                  dependencies=[
                    'foo/bar'
                  ],
                  provides=setup_py(
                    name='foo1',
                    version='0.0.0'
                  )
                )
                python_library(
                  name='foo2',
                  sources=[],
                  dependencies=[
                    'foo/bar'
                  ],
                  provides=setup_py(
                    name='foo2',
                    version='0.0.0'
                  )
                )
                """
            ),
        )

        with self.assertRaises(self.dependency_calculator.AmbiguousOwnerError):
            self.dependency_calculator.reduced_dependencies(self.target("foo:foo1"))

        with self.assertRaises(self.dependency_calculator.AmbiguousOwnerError):
            self.dependency_calculator.reduced_dependencies(self.target("foo:foo2"))

    @contextmanager
    def extracted_sdist(self, sdist, expected_prefix, collect_suffixes=None):
        collect_suffixes = collect_suffixes or (".py",)

        def collect(path):
            for suffix in collect_suffixes:
                if path.endswith(suffix):
                    return True
            return False

        with temporary_dir() as chroot:
            TGZ.extract(sdist, chroot)

            all_py_files = set()
            for root, _, files in os.walk(chroot):
                all_py_files.update(os.path.join(root, f) for f in files if collect(f))

            def as_full_path(p):
                return os.path.join(chroot, expected_prefix, p)

            yield all_py_files, as_full_path

    def test_resources(self):
        self.create_file(relpath="src/python/monster/j-function.res", contents="196884")
        self.create_file(relpath="src/python/monster/__init__.py", contents="")
        self.create_file(
            relpath="src/python/monster/research_programme.py",
            contents='# Look for more off-by-one "errors"!',
        )

        # NB: We have to resort to BUILD files on disk here due to the target ownership algorithm in
        # SetupPy needing to walk ancestors in this case which currently requires BUILD files on disk.
        self.add_to_build_file(
            "src/python/monster",
            dedent(
                """
                python_library(
                  name='conway',
                  sources=['__init__.py', 'research_programme.py'],
                  dependencies=[
                    ':j-function',
                  ],
                  provides=setup_py(
                    name='monstrous.moonshine',
                    version='0.0.0',
                  )
                )

                resources(
                  name='j-function',
                  sources=['j-function.res']
                )
                """
            ),
        )
        conway = self.target("src/python/monster:conway")

        with self.run_execute(conway) as created:
            self.assertEqual([conway], list(created.keys()))
            sdist = created[conway]

            with self.extracted_sdist(
                sdist=sdist,
                expected_prefix="monstrous.moonshine-0.0.0",
                collect_suffixes=(".py", ".res"),
            ) as (py_files, path):
                self.assertEqual(
                    {
                        path("setup.py"),
                        path("src/monster/__init__.py"),
                        path("src/monster/research_programme.py"),
                        path("src/monster/j-function.res"),
                    },
                    py_files,
                )

                with open(path("src/monster/j-function.res"), "r") as fp:
                    self.assertEqual("196884", fp.read())

    def test_symlinks_issues_2815(self):
        res = self.create_file(relpath="src/python/monster/j-function.res", contents="196884")

        self.create_link(res, "src/python/monster/group.res")
        self.create_file(relpath="src/python/monster/__init__.py", contents="")
        self.create_file(
            relpath="src/python/monster/research_programme.py",
            contents='# Look for more off-by-one "errors"!',
        )

        # NB: We have to resort to BUILD files on disk here due to the target ownership algorithm in
        # SetupPy needing to walk ancestors in this case which currently requires BUILD files on disk.
        self.add_to_build_file(
            "src/python/monster",
            dedent(
                """
                python_library(
                  name='conway',
                  sources=['__init__.py', 'research_programme.py'],
                  dependencies=[
                    ':group_res',
                  ],
                  provides=setup_py(
                    name='monstrous.moonshine',
                    version='0.0.0',
                  )
                )

                resources(
                  name='group_res',
                  sources=['group.res']
                )
                """
            ),
        )
        conway = self.target("src/python/monster:conway")

        with self.run_execute(conway) as created:
            self.assertEqual([conway], list(created.keys()))

            # Now that we've created the sdist tarball, delete the symlink destination to ensure the
            # unpacked sdist can't get away with unpacking a symlink that happens to have local
            # resolution.
            os.unlink(res)
            sdist = created[conway]

            with self.extracted_sdist(
                sdist=sdist,
                expected_prefix="monstrous.moonshine-0.0.0",
                collect_suffixes=(".py", ".res"),
            ) as (py_files, path):
                res_link_path = path("src/monster/group.res")
                self.assertFalse(os.path.islink(res_link_path))

                self.assertEqual(
                    {
                        path("setup.py"),
                        path("src/monster/__init__.py"),
                        path("src/monster/research_programme.py"),
                        res_link_path,
                    },
                    py_files,
                )

                with open(res_link_path, "r") as fp:
                    self.assertEqual("196884", fp.read())

    def test_prep_command_case(self):
        PrepCommand.add_allowed_goal("compile")
        PrepCommand.add_allowed_goal("test")
        self.add_to_build_file(
            "build-support/thrift",
            dedent(
                """
                prep_command(
                  name='prepare_binary_compile',
                  goals=['compile'],
                  prep_executable='/bin/true',
                )

                prep_command(
                  name='prepare_binary_test',
                  goals=['test'],
                  prep_executable='/bin/true',
                )

                target(
                  name='prepare_binary',
                  dependencies=[
                    ':prepare_binary_compile',
                    ':prepare_binary_test',
                  ],
                )
                """
            ),
        )
        prepare_binary_compile = self.make_target(
            spec="build-support/thrift:prepare_binary_compile",
            target_type=PrepCommand,
            prep_executable="/bin/true",
            goals=["compile"],
        )
        prepare_binary_test = self.make_target(
            spec="build-support/thrift:prepare_binary_test",
            target_type=PrepCommand,
            prep_executable="/bin/true",
            goals=["test"],
        )
        self.make_target(
            spec="build-support/thrift:prepare_binary",
            dependencies=[prepare_binary_compile, prepare_binary_test],
        )

        pants = self.create_python_library(
            relpath="src/python/pants",
            name="pants",
            provides="setup_py(name='pants', version='0.0.0')",
            dependencies=["build-support/thrift:prepare_binary"],
        )
        with self.run_execute(pants) as created:
            self.assertEqual([pants], list(created.keys()))

    def test_run_invalid_cmd_failure(self):
        self.set_options(run="invalid_command")
        with self.assertRaises(TaskError):
            self.run_execute(
                self.create_python_library(
                    relpath="foo", name="foo", provides="setup_py(name='foo', version='0.0.0')",
                )
            ).__enter__()


def test_detect_namespace_packages():
    def has_ns(stmt):
        with temporary_file(binary_mode=False) as fp:
            fp.write(stmt)
            fp.flush()
            return declares_namespace_package(fp.name)

    assert not has_ns("")
    assert not has_ns("add(1, 2); foo(__name__); self.shoot(__name__)")
    assert not has_ns("declare_namespace(bonk)")
    assert has_ns(
        '__import__("pkg_resources").declare_namespace(__name__)  # type: ignore[attr-defined]'
    )
    assert has_ns("import pkg_resources; pkg_resources.declare_namespace(__name__)")
    assert has_ns("from pkg_resources import declare_namespace; declare_namespace(__name__)")


class TestSetupPyFindPackages(SetupPyTestBase):
    @contextmanager
    def yield_chroot(self, packages, namespace_packages, resources, py3=False):
        def to_path(package):
            return package.replace(".", os.path.sep)

        with temporary_dir() as td:

            def write(package, name, content):
                package_path = os.path.join(td, SetupPy.SOURCE_ROOT, to_path(package))
                safe_mkdir(os.path.dirname(os.path.join(package_path, name)))
                with open(os.path.join(package_path, name), "w") as fp:
                    fp.write(content)

            for package in packages:
                write(package, "__init__.py", 'a = "b"; b = f"{a}"' if py3 else "")
            for package in namespace_packages:
                write(
                    package,
                    "__init__.py",
                    '__import__("pkg_resources").declare_namespace(__name__)  # type: ignore[attr-defined]',
                )
            for package, resource_list in resources.items():
                for resource in resource_list:
                    write(package, resource, "asdfasdf")

            chroot_mock = Mock(spec=Chroot)
            chroot_mock.path.return_value = td
            yield chroot_mock

    def assert_find_packages(self, py36):
        compatibility = "CPython>=3.6,<3.7" if py36 else "CPython>=2.7,<3"
        dummy_target = self.make_target(
            spec="src/python/foo",
            target_type=PythonLibrary,
            sources=[],
            compatibility=compatibility,
        )
        setup_py = self.prepare_setup_py(dummy_target)

        def assert_single_chroot(packages, namespace_packages, resources):
            with self.yield_chroot(packages, namespace_packages, resources, py3=py36) as chroot:
                p, n_p, r = setup_py.find_packages(dummy_target, chroot)
                assert p == set(packages + namespace_packages)
                assert n_p == set(namespace_packages)
                assert r == dict((k, set(v)) for (k, v) in resources.items())

        # assert both packages and namespace packages work
        assert_single_chroot(["foo"], [], {})
        assert_single_chroot(["foo"], ["foo"], {})

        # assert resources work
        assert_single_chroot(["foo"], [], {"foo": ["blork.dat"]})

        resources = {
            "foo": ["f0", os.path.join("bar", "baz", "f1"), os.path.join("bar", "baz", "f2")]
        }
        assert_single_chroot(["foo"], [], resources)

        # assert that nearest-submodule is honored
        with self.yield_chroot(["foo", "foo.bar"], [], resources, py3=py36) as chroot:
            _, _, r = setup_py.find_packages(dummy_target, chroot)
            assert r == {
                "foo": {"f0"},
                "foo.bar": {os.path.join("baz", "f1"), os.path.join("baz", "f2")},
            }

        # assert that nearest submodule splits on module prefixes
        with self.yield_chroot(["foo", "foo.bar"], [], {"foo.bar1": ["f0"]}, py3=py36) as chroot:
            _, _, r = setup_py.find_packages(dummy_target, chroot)
            assert r == {"foo": {"bar1/f0"}}

    def test_find_packages(self):
        self.assert_find_packages(py36=False)

    @skip_unless_python36_present
    def test_find_packages_py3(self):
        self.assert_find_packages(py36=True)


def test_nearest_subpackage():
    # degenerate
    assert SetupPy.nearest_subpackage("foo", []) == "foo"
    assert SetupPy.nearest_subpackage("foo", ["foo"]) == "foo"
    assert SetupPy.nearest_subpackage("foo", ["bar"]) == "foo"

    # common prefix
    assert "foo" == SetupPy.nearest_subpackage("foo.bar", ["foo"])
    assert "foo.bar" == SetupPy.nearest_subpackage("foo.bar", ["foo", "foo.bar"])
    assert "foo.bar" == SetupPy.nearest_subpackage("foo.bar.topo", ["foo", "foo.bar"])
    assert "foo" == SetupPy.nearest_subpackage("foo.barization", ["foo", "foo.bar"])
