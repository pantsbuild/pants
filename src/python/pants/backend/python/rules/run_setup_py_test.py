# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import textwrap
from typing import Iterable, Type

import pytest

from pants.backend.python.python_artifact import PythonArtifact
from pants.backend.python.rules.run_setup_py import (
    AmbiguousOwnerError,
    AncestorInitPyFiles,
    DependencyOwner,
    ExportedTarget,
    ExportedTargetRequirements,
    InvalidEntryPoint,
    InvalidSetupPyArgs,
    NoOwnerError,
    OwnedDependencies,
    OwnedDependency,
    SetupPyChroot,
    SetupPyChrootRequest,
    SetupPySources,
    SetupPySourcesRequest,
    generate_chroot,
    get_ancestor_init_py,
    get_exporting_owner,
    get_owned_dependencies,
    get_requirements,
    get_sources,
    validate_args,
)
from pants.backend.python.target_types import PythonBinary, PythonLibrary, PythonRequirementLibrary
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.core.target_types import Resources
from pants.core.util_rules.determine_source_files import rules as determine_source_files_rules
from pants.core.util_rules.strip_source_roots import rules as strip_source_roots_rules
from pants.engine.addresses import Address
from pants.engine.fs import Snapshot
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.engine.target import Target, Targets, WrappedTarget
from pants.python.python_requirement import PythonRequirement
from pants.source.source_root import SourceRootConfig
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.subsystem.util import init_subsystem
from pants.testutil.test_base import TestBase

_namespace_decl = "__import__('pkg_resources').declare_namespace(__name__)"


class TestSetupPyBase(TestBase):
    @classmethod
    def alias_groups(cls) -> BuildFileAliases:
        return BuildFileAliases(
            objects={"python_requirement": PythonRequirement, "setup_py": PythonArtifact}
        )

    @classmethod
    def target_types(cls):
        return [PythonBinary, PythonLibrary, PythonRequirementLibrary, Resources]

    def tgt(self, addr: str) -> Target:
        return self.request_single_product(WrappedTarget, Params(Address.parse(addr))).target


def init_source_root():
    init_subsystem(SourceRootConfig, options={"source": {"root_patterns": ["src/python"]}})


class TestGenerateChroot(TestSetupPyBase):
    @classmethod
    def rules(cls):
        return super().rules() + [
            generate_chroot,
            get_sources,
            get_requirements,
            get_ancestor_init_py,
            get_owned_dependencies,
            get_exporting_owner,
            RootRule(SetupPyChrootRequest),
            *determine_source_files_rules(),
            *strip_source_roots_rules(),
        ]

    def assert_chroot(self, expected_files, expected_setup_kwargs, addr):
        chroot = self.request_single_product(
            SetupPyChroot,
            Params(
                SetupPyChrootRequest(ExportedTarget(self.tgt(addr)), py2=False),
                create_options_bootstrapper(args=["--source-root-patterns=src/python"]),
            ),
        )
        snapshot = self.request_single_product(Snapshot, Params(chroot.digest))
        assert sorted(expected_files) == sorted(snapshot.files)
        kwargs = json.loads(chroot.setup_keywords_json)
        assert expected_setup_kwargs == kwargs

    def assert_error(self, addr: str, exc_cls: Type[Exception]):
        with pytest.raises(ExecutionError) as excinfo:
            self.request_single_product(
                SetupPyChroot,
                Params(
                    SetupPyChrootRequest(ExportedTarget(self.tgt(addr)), py2=False),
                    create_options_bootstrapper(args=["--source-root-patterns=src/python"]),
                ),
            )
        ex = excinfo.value
        assert len(ex.wrapped_exceptions) == 1
        assert type(ex.wrapped_exceptions[0]) == exc_cls

    def test_generate_chroot(self) -> None:
        init_source_root()
        self.create_file(
            "src/python/foo/bar/baz/BUILD",
            "python_library(provides=setup_py(name='baz', version='1.1.1'))",
        )
        self.create_file("src/python/foo/bar/baz/baz.py", "")
        self.create_file(
            "src/python/foo/qux/BUILD",
            textwrap.dedent(
                """
                python_library()
                python_binary(name="bin", entry_point="foo.qux.bin")
                """
            ),
        )
        self.create_file("src/python/foo/qux/__init__.py", "")
        self.create_file("src/python/foo/qux/qux.py", "")
        self.create_file("src/python/foo/resources/BUILD", 'resources(sources=["js/code.js"])')
        self.create_file("src/python/foo/resources/js/code.js", "")
        self.create_file(
            "src/python/foo/BUILD",
            textwrap.dedent(
                """
                python_library(
                    dependencies=[
                        'src/python/foo/bar/baz',
                        'src/python/foo/qux',
                        'src/python/foo/resources',
                    ],
                    provides=setup_py(
                        name='foo', version='1.2.3'
                    ).with_binaries(
                        foo_main='src/python/foo/qux:bin'
                    )
                )
                """
            ),
        )
        self.create_file("src/python/foo/__init__.py", _namespace_decl)
        self.create_file("src/python/foo/foo.py", "")
        self.assert_chroot(
            [
                "src/foo/qux/__init__.py",
                "src/foo/qux/qux.py",
                "src/foo/resources/js/code.js",
                "src/foo/__init__.py",
                "src/foo/foo.py",
                "setup.py",
                "MANIFEST.in",
            ],
            {
                "name": "foo",
                "version": "1.2.3",
                "package_dir": {"": "src"},
                "packages": ["foo", "foo.qux"],
                "namespace_packages": ["foo"],
                "package_data": {"foo": ["resources/js/code.js"]},
                "install_requires": ["baz==1.1.1"],
                "entry_points": {"console_scripts": ["foo_main=foo.qux.bin"]},
            },
            "src/python/foo",
        )

    def test_invalid_binary(self) -> None:
        init_source_root()
        self.create_file(
            "src/python/invalid_binary/BUILD",
            textwrap.dedent(
                """
                python_library(name='not_a_binary', sources=[])
                python_binary(name='no_entrypoint')
                python_library(
                    name='invalid_bin1',
                    sources=[],
                    provides=setup_py(
                        name='invalid_bin1', version='1.1.1'
                    ).with_binaries(foo=':not_a_binary')
                )
                python_library(
                    name='invalid_bin2',
                    sources=[],
                    provides=setup_py(
                        name='invalid_bin2', version='1.1.1'
                    ).with_binaries(foo=':no_entrypoint')
                )
                """
            ),
        )

        self.assert_error("src/python/invalid_binary:invalid_bin1", InvalidEntryPoint)
        self.assert_error("src/python/invalid_binary:invalid_bin2", InvalidEntryPoint)


class TestGetSources(TestSetupPyBase):
    @classmethod
    def rules(cls):
        return super().rules() + [
            get_sources,
            get_ancestor_init_py,
            RootRule(SetupPySourcesRequest),
            RootRule(SourceRootConfig),
            *determine_source_files_rules(),
            *strip_source_roots_rules(),
        ]

    def assert_sources(
        self,
        expected_files,
        expected_packages,
        expected_namespace_packages,
        expected_package_data,
        addrs,
    ):
        srcs = self.request_single_product(
            SetupPySources,
            Params(
                SetupPySourcesRequest(Targets([self.tgt(addr) for addr in addrs]), py2=False),
                SourceRootConfig.global_instance(),
            ),
        )
        chroot_snapshot = self.request_single_product(Snapshot, Params(srcs.digest))

        assert sorted(expected_files) == sorted(chroot_snapshot.files)
        assert sorted(expected_packages) == sorted(srcs.packages)
        assert sorted(expected_namespace_packages) == sorted(srcs.namespace_packages)
        assert expected_package_data == dict(srcs.package_data)

    def test_get_sources(self) -> None:
        init_source_root()
        self.create_file(
            "src/python/foo/bar/baz/BUILD",
            textwrap.dedent(
                """
                python_library(name='baz1', sources=['baz1.py'])
                python_library(name='baz2', sources=['baz2.py'])
                """
            ),
        )
        self.create_file("src/python/foo/bar/baz/baz1.py", "")
        self.create_file("src/python/foo/bar/baz/baz2.py", "")
        self.create_file("src/python/foo/bar/__init__.py", _namespace_decl)
        self.create_file("src/python/foo/qux/BUILD", "python_library()")
        self.create_file("src/python/foo/qux/__init__.py", "")
        self.create_file("src/python/foo/qux/qux.py", "")
        self.create_file("src/python/foo/resources/BUILD", 'resources(sources=["js/code.js"])')
        self.create_file("src/python/foo/resources/js/code.js", "")
        self.create_file("src/python/foo/__init__.py", "")

        self.assert_sources(
            expected_files=["foo/bar/baz/baz1.py", "foo/bar/__init__.py", "foo/__init__.py"],
            expected_packages=["foo", "foo.bar", "foo.bar.baz"],
            expected_namespace_packages=["foo.bar"],
            expected_package_data={},
            addrs=["src/python/foo/bar/baz:baz1"],
        )

        self.assert_sources(
            expected_files=["foo/bar/baz/baz2.py", "foo/bar/__init__.py", "foo/__init__.py"],
            expected_packages=["foo", "foo.bar", "foo.bar.baz"],
            expected_namespace_packages=["foo.bar"],
            expected_package_data={},
            addrs=["src/python/foo/bar/baz:baz2"],
        )

        self.assert_sources(
            expected_files=["foo/qux/qux.py", "foo/qux/__init__.py", "foo/__init__.py"],
            expected_packages=["foo", "foo.qux"],
            expected_namespace_packages=[],
            expected_package_data={},
            addrs=["src/python/foo/qux"],
        )

        self.assert_sources(
            expected_files=[
                "foo/bar/baz/baz1.py",
                "foo/bar/__init__.py",
                "foo/qux/qux.py",
                "foo/qux/__init__.py",
                "foo/__init__.py",
                "foo/resources/js/code.js",
            ],
            expected_packages=["foo", "foo.bar", "foo.bar.baz", "foo.qux"],
            expected_namespace_packages=["foo.bar"],
            expected_package_data={"foo": ("resources/js/code.js",)},
            addrs=["src/python/foo/bar/baz:baz1", "src/python/foo/qux", "src/python/foo/resources"],
        )

        self.assert_sources(
            expected_files=[
                "foo/bar/baz/baz1.py",
                "foo/bar/baz/baz2.py",
                "foo/bar/__init__.py",
                "foo/qux/qux.py",
                "foo/qux/__init__.py",
                "foo/__init__.py",
                "foo/resources/js/code.js",
            ],
            expected_packages=["foo", "foo.bar", "foo.bar.baz", "foo.qux"],
            expected_namespace_packages=["foo.bar"],
            expected_package_data={"foo": ("resources/js/code.js",)},
            addrs=[
                "src/python/foo/bar/baz:baz1",
                "src/python/foo/bar/baz:baz2",
                "src/python/foo/qux",
                "src/python/foo/resources",
            ],
        )


class TestGetRequirements(TestSetupPyBase):
    @classmethod
    def rules(cls):
        return super().rules() + [
            get_requirements,
            get_owned_dependencies,
            get_exporting_owner,
            RootRule(DependencyOwner),
        ]

    def assert_requirements(self, expected_req_strs, addr):
        reqs = self.request_single_product(
            ExportedTargetRequirements,
            Params(DependencyOwner(ExportedTarget(self.tgt(addr))), create_options_bootstrapper()),
        )
        assert sorted(expected_req_strs) == list(reqs)

    def test_get_requirements(self) -> None:
        self.create_file(
            "3rdparty/BUILD",
            textwrap.dedent(
                """
                python_requirement_library(
                    name='ext1',
                    requirements=[python_requirement('ext1==1.22.333')],
                )
                python_requirement_library(
                    name='ext2',
                    requirements=[python_requirement('ext2==4.5.6')],
                )
                python_requirement_library(
                    name='ext3',
                    requirements=[python_requirement('ext3==0.0.1')],
                )
                """
            ),
        )
        self.create_file(
            "src/python/foo/bar/baz/BUILD",
            "python_library(dependencies=['3rdparty:ext1'], sources=[])",
        )
        self.create_file(
            "src/python/foo/bar/qux/BUILD",
            "python_library(dependencies=['3rdparty:ext2', 'src/python/foo/bar/baz'], sources=[])",
        )
        self.create_file(
            "src/python/foo/bar/BUILD",
            textwrap.dedent(
                """
                python_library(
                    sources=[],
                    dependencies=['src/python/foo/bar/baz', 'src/python/foo/bar/qux'],
                    provides=setup_py(name='bar', version='9.8.7'),
                )
              """
            ),
        )
        self.create_file(
            "src/python/foo/corge/BUILD",
            textwrap.dedent(
                """
                python_library(
                    sources=[],
                    dependencies=['3rdparty:ext3', 'src/python/foo/bar'],
                    provides=setup_py(name='corge', version='2.2.2'),
                )
                """
            ),
        )

        self.assert_requirements(["ext1==1.22.333", "ext2==4.5.6"], "src/python/foo/bar")
        self.assert_requirements(["ext3==0.0.1", "bar==9.8.7"], "src/python/foo/corge")


class TestGetAncestorInitPy(TestSetupPyBase):
    @classmethod
    def rules(cls):
        return super().rules() + [
            get_ancestor_init_py,
            RootRule(Targets),
            RootRule(SourceRootConfig),
            *determine_source_files_rules(),
        ]

    def assert_ancestor_init_py(
        self, expected_init_pys: Iterable[str], addrs: Iterable[str]
    ) -> None:
        ancestor_init_py_files = self.request_single_product(
            AncestorInitPyFiles,
            Params(
                Targets([self.tgt(addr) for addr in addrs]), SourceRootConfig.global_instance(),
            ),
        )
        snapshots = [
            self.request_single_product(Snapshot, Params(digest))
            for digest in ancestor_init_py_files.digests
        ]
        init_py_files_found = set([file for snapshot in snapshots for file in snapshot.files])
        # NB: Doesn't include the root __init__.py or the missing src/python/foo/bar/__init__.py.
        assert sorted(expected_init_pys) == sorted(init_py_files_found)

    def test_get_ancestor_init_py(self) -> None:
        init_source_root()
        # NB: src/python/foo/bar/baz/qux/__init__.py is a target's source.
        self.create_file("src/python/foo/bar/baz/qux/BUILD", "python_library()")
        self.create_file("src/python/foo/bar/baz/qux/qux.py", "")
        self.create_file("src/python/foo/bar/baz/qux/__init__.py", "")
        self.create_file("src/python/foo/bar/baz/__init__.py", "")
        # NB: No src/python/foo/bar/__init__.py.
        # NB: src/python/foo/corge/__init__.py is not any target's source.
        self.create_file("src/python/foo/corge/BUILD", 'python_library(sources=["corge.py"])')
        self.create_file("src/python/foo/corge/corge.py", "")
        self.create_file("src/python/foo/corge/__init__.py", "")
        self.create_file("src/python/foo/__init__.py", "")
        self.create_file("src/python/__init__.py", "")
        self.create_file("src/python/foo/resources/BUILD", 'resources(sources=["style.css"])')
        self.create_file("src/python/foo/resources/style.css", "")
        # NB: A stray __init__.py in a resources-only dir.
        self.create_file("src/python/foo/resources/__init__.py", "")

        # NB: None of these should include the root src/python/__init__.py, the missing
        # src/python/foo/bar/__init__.py, or the stray src/python/foo/resources/__init__.py.
        self.assert_ancestor_init_py(
            ["foo/bar/baz/qux/__init__.py", "foo/bar/baz/__init__.py", "foo/__init__.py"],
            ["src/python/foo/bar/baz/qux"],
        )
        self.assert_ancestor_init_py([], ["src/python/foo/resources"])
        self.assert_ancestor_init_py(
            ["foo/corge/__init__.py", "foo/__init__.py"],
            ["src/python/foo/corge", "src/python/foo/resources"],
        )

        self.assert_ancestor_init_py(
            [
                "foo/bar/baz/qux/__init__.py",
                "foo/bar/baz/__init__.py",
                "foo/corge/__init__.py",
                "foo/__init__.py",
            ],
            ["src/python/foo/bar/baz/qux", "src/python/foo/corge"],
        )


class TestGetOwnedDependencies(TestSetupPyBase):
    @classmethod
    def rules(cls):
        return super().rules() + [
            get_owned_dependencies,
            get_exporting_owner,
            RootRule(DependencyOwner),
        ]

    def assert_owned(self, owned: Iterable[str], exported: str):
        assert sorted(owned) == sorted(
            od.target.address.reference()
            for od in self.request_single_product(
                OwnedDependencies,
                Params(
                    DependencyOwner(ExportedTarget(self.tgt(exported))),
                    create_options_bootstrapper(),
                ),
            )
        )

    def test_owned_dependencies(self) -> None:
        self.create_file(
            "src/python/foo/bar/baz/BUILD",
            textwrap.dedent(
                """
                python_library(name='baz1', sources=[])
                python_library(name='baz2', sources=[])
                """
            ),
        )
        self.create_file(
            "src/python/foo/bar/BUILD",
            textwrap.dedent(
                """
                python_library(
                    name='bar1',
                    sources=[],
                    dependencies=['src/python/foo/bar/baz:baz1'],
                    provides=setup_py(name='bar1', version='1.1.1'),
                )
                python_library(
                    name='bar2',
                    sources=[],
                    dependencies=[':bar-resources', 'src/python/foo/bar/baz:baz2'],
                )
                resources(name='bar-resources', sources=[])
                """
            ),
        )
        self.create_file(
            "src/python/foo/BUILD",
            textwrap.dedent(
                """
                python_library(
                    name='foo',
                    sources=[],
                    dependencies=['src/python/foo/bar:bar1', 'src/python/foo/bar:bar2'],
                    provides=setup_py(name='foo', version='3.4.5'),
                )
                """
            ),
        )

        self.assert_owned(
            ["src/python/foo/bar:bar1", "src/python/foo/bar/baz:baz1"], "src/python/foo/bar:bar1"
        )
        self.assert_owned(
            [
                "src/python/foo",
                "src/python/foo/bar:bar2",
                "src/python/foo/bar:bar-resources",
                "src/python/foo/bar/baz:baz2",
            ],
            "src/python/foo",
        )


class TestGetExportingOwner(TestSetupPyBase):
    @classmethod
    def rules(cls):
        return super().rules() + [
            get_exporting_owner,
            RootRule(OwnedDependency),
        ]

    def assert_is_owner(self, owner: str, owned: str):
        assert (
            owner
            == self.request_single_product(
                ExportedTarget,
                Params(OwnedDependency(self.tgt(owned)), create_options_bootstrapper()),
            ).target.address.reference()
        )

    def assert_error(self, owned: str, exc_cls: Type[Exception]):
        with pytest.raises(ExecutionError) as excinfo:
            self.request_single_product(
                ExportedTarget,
                Params(OwnedDependency(self.tgt(owned)), create_options_bootstrapper()),
            )
        ex = excinfo.value
        assert len(ex.wrapped_exceptions) == 1
        assert type(ex.wrapped_exceptions[0]) == exc_cls

    def assert_no_owner(self, owned: str):
        self.assert_error(owned, NoOwnerError)

    def assert_ambiguous_owner(self, owned: str):
        self.assert_error(owned, AmbiguousOwnerError)

    def test_get_owner_simple(self) -> None:
        self.create_file(
            "src/python/foo/bar/baz/BUILD",
            textwrap.dedent(
                """
                python_library(name='baz1', sources=[])
                python_library(name='baz2', sources=[])
                """
            ),
        )
        self.create_file(
            "src/python/foo/bar/BUILD",
            textwrap.dedent(
                """
                python_library(
                    name='bar1',
                    sources=[],
                    dependencies=['src/python/foo/bar/baz:baz1'],
                    provides=setup_py(name='bar1', version='1.1.1'),
                )
                python_library(
                    name='bar2',
                    sources=[],
                    dependencies=[':bar-resources', 'src/python/foo/bar/baz:baz2'],
                )
                resources(name='bar-resources', sources=[])
                """
            ),
        )
        self.create_file(
            "src/python/foo/BUILD",
            textwrap.dedent(
                """
                python_library(
                    name='foo1',
                    sources=[],
                    dependencies=['src/python/foo/bar/baz:baz2'],
                    provides=setup_py(name='foo1', version='0.1.2'),
                )
                python_library(name='foo2', sources=[])
                python_library(
                    name='foo3',
                    sources=[],
                    dependencies=['src/python/foo/bar:bar2'],
                    provides=setup_py(name='foo3', version='3.4.5'),
                )
                """
            ),
        )

        self.assert_is_owner("src/python/foo/bar:bar1", "src/python/foo/bar:bar1")
        self.assert_is_owner("src/python/foo/bar:bar1", "src/python/foo/bar/baz:baz1")

        self.assert_is_owner("src/python/foo:foo1", "src/python/foo:foo1")

        self.assert_is_owner("src/python/foo:foo3", "src/python/foo:foo3")
        self.assert_is_owner("src/python/foo:foo3", "src/python/foo/bar:bar2")
        self.assert_is_owner("src/python/foo:foo3", "src/python/foo/bar:bar-resources")

        self.assert_no_owner("src/python/foo:foo2")
        self.assert_ambiguous_owner("src/python/foo/bar/baz:baz2")

    def test_get_owner_siblings(self) -> None:
        self.create_file(
            "src/python/siblings/BUILD",
            textwrap.dedent(
                """
                python_library(name='sibling1', sources=[])
                python_library(
                    name='sibling2',
                    sources=[],
                    dependencies=['src/python/siblings:sibling1'],
                    provides=setup_py(name='siblings', version='2.2.2'),
                )
                """
            ),
        )

        self.assert_is_owner("src/python/siblings:sibling2", "src/python/siblings:sibling1")
        self.assert_is_owner("src/python/siblings:sibling2", "src/python/siblings:sibling2")

    def test_get_owner_not_an_ancestor(self) -> None:
        self.create_file(
            "src/python/notanancestor/aaa/BUILD",
            textwrap.dedent(
                """
                python_library(name='aaa', sources=[])
                """
            ),
        )
        self.create_file(
            "src/python/notanancestor/bbb/BUILD",
            textwrap.dedent(
                """
                python_library(
                    name='bbb',
                    sources=[],
                    dependencies=['src/python/notanancestor/aaa'],
                    provides=setup_py(name='bbb', version='11.22.33'),
                )
                """
            ),
        )

        self.assert_no_owner("src/python/notanancestor/aaa")
        self.assert_is_owner("src/python/notanancestor/bbb", "src/python/notanancestor/bbb")

    def test_get_owner_multiple_ancestor_generations(self) -> None:
        self.create_file(
            "src/python/aaa/bbb/ccc/BUILD",
            textwrap.dedent(
                """
                python_library(name='ccc', sources=[])
                """
            ),
        )
        self.create_file(
            "src/python/aaa/bbb/BUILD",
            textwrap.dedent(
                """
                python_library(
                    name='bbb',
                    sources=[],
                    dependencies=['src/python/aaa/bbb/ccc'],
                    provides=setup_py(name='bbb', version='1.1.1'),
                )
                """
            ),
        )
        self.create_file(
            "src/python/aaa/BUILD",
            textwrap.dedent(
                """
                python_library(
                    name='aaa',
                    sources=[],
                    dependencies=['src/python/aaa/bbb/ccc'],
                    provides=setup_py(name='aaa', version='2.2.2'),
                )
                """
            ),
        )

        self.assert_is_owner("src/python/aaa/bbb", "src/python/aaa/bbb/ccc")
        self.assert_is_owner("src/python/aaa/bbb", "src/python/aaa/bbb")
        self.assert_is_owner("src/python/aaa", "src/python/aaa")


def test_validate_args() -> None:
    with pytest.raises(InvalidSetupPyArgs):
        validate_args(("bdist_wheel", "upload"))
    with pytest.raises(InvalidSetupPyArgs):
        validate_args(("sdist", "-d", "new_distdir/"))
    with pytest.raises(InvalidSetupPyArgs):
        validate_args(("--dist-dir", "new_distdir/", "sdist"))

    validate_args(("sdist",))
    validate_args(("bdist_wheel", "--foo"))
