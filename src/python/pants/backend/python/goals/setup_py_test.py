# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import textwrap
from typing import Iterable

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.goals.setup_py import (
    AmbiguousOwnerError,
    DependencyOwner,
    DistBuildChroot,
    DistBuildChrootRequest,
    DistBuildSources,
    ExportedTarget,
    ExportedTargetRequirements,
    FinalizedSetupKwargs,
    FirstPartyDependencyVersionScheme,
    GenerateSetupPyRequest,
    InvalidEntryPoint,
    InvalidSetupPyArgs,
    NoOwnerError,
    OwnedDependencies,
    OwnedDependency,
    SetupKwargs,
    SetupKwargsRequest,
    SetupPyGeneration,
    declares_pkg_resources_namespace_package,
    determine_setup_kwargs,
    generate_chroot,
    generate_setup_py,
    generate_setup_py_kwargs,
    get_exporting_owner,
    get_owned_dependencies,
    get_requirements,
    get_sources,
    merge_entry_points,
    validate_commands,
)
from pants.backend.python.macros.python_artifact import PythonArtifact
from pants.backend.python.target_types import (
    PexBinary,
    PythonDistribution,
    PythonRequirementTarget,
    PythonSourcesGeneratorTarget,
)
from pants.backend.python.util_rules import python_sources
from pants.core.target_types import FileTarget, ResourceTarget
from pants.engine.addresses import Address
from pants.engine.fs import Snapshot
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.rules import SubsystemRule, rule
from pants.engine.unions import UnionRule
from pants.testutil.rule_runner import QueryRule, RuleRunner

_namespace_decl = "__import__('pkg_resources').declare_namespace(__name__)"


def create_setup_py_rule_runner(*, rules: Iterable) -> RuleRunner:
    rule_runner = RuleRunner(
        rules=rules,
        target_types=[
            PexBinary,
            PythonDistribution,
            PythonSourcesGeneratorTarget,
            PythonRequirementTarget,
            ResourceTarget,
            FileTarget,
        ],
        objects={"setup_py": PythonArtifact},
    )
    rule_runner.set_options([], env_inherit={"PATH", "PYENV_ROOT", "HOME"})
    return rule_runner


# We use a trivial test that our SetupKwargs plugin hook works.
class PluginSetupKwargsRequest(SetupKwargsRequest):
    @classmethod
    def is_applicable(cls, _) -> bool:
        return True


@rule
def setup_kwargs_plugin(request: PluginSetupKwargsRequest) -> SetupKwargs:
    if "setup_script" in request.explicit_kwargs:
        kwargs = request.explicit_kwargs
    else:
        kwargs = {**request.explicit_kwargs, "plugin_demo": "hello world"}
    return SetupKwargs(kwargs, address=request.target.address)


@pytest.fixture
def chroot_rule_runner() -> RuleRunner:
    return create_setup_py_rule_runner(
        rules=[
            determine_setup_kwargs,
            generate_chroot,
            generate_setup_py,
            generate_setup_py_kwargs,
            get_sources,
            get_requirements,
            get_owned_dependencies,
            get_exporting_owner,
            *python_sources.rules(),
            *target_types_rules.rules(),
            setup_kwargs_plugin,
            SubsystemRule(SetupPyGeneration),
            UnionRule(SetupKwargsRequest, PluginSetupKwargsRequest),
            QueryRule(DistBuildChroot, (DistBuildChrootRequest,)),
            QueryRule(DistBuildSources, (DistBuildChrootRequest,)),
            QueryRule(FinalizedSetupKwargs, (GenerateSetupPyRequest,)),
        ]
    )


def assert_chroot(
    rule_runner: RuleRunner,
    expected_files: list[str],
    expected_setup_kwargs,
    addr: Address,
) -> None:
    tgt = rule_runner.get_target(addr)
    req = DistBuildChrootRequest(ExportedTarget(tgt), py2=False)
    chroot = rule_runner.request(DistBuildChroot, [req])
    snapshot = rule_runner.request(Snapshot, [chroot.digest])
    assert sorted(expected_files) == sorted(snapshot.files)

    if expected_setup_kwargs is not None:
        sources = rule_runner.request(DistBuildSources, [req])
        setup_kwargs = rule_runner.request(
            FinalizedSetupKwargs, [GenerateSetupPyRequest(ExportedTarget(tgt), sources)]
        )
        assert expected_setup_kwargs == setup_kwargs.kwargs


def assert_chroot_error(rule_runner: RuleRunner, addr: Address, exc_cls: type[Exception]) -> None:
    tgt = rule_runner.get_target(addr)
    with pytest.raises(ExecutionError) as excinfo:
        rule_runner.request(
            DistBuildChroot,
            [DistBuildChrootRequest(ExportedTarget(tgt), py2=False)],
        )
    ex = excinfo.value
    assert len(ex.wrapped_exceptions) == 1
    assert type(ex.wrapped_exceptions[0]) == exc_cls


def test_use_existing_setup_script(chroot_rule_runner) -> None:
    chroot_rule_runner.add_to_build_file("src/python/foo/bar", "python_sources()")
    chroot_rule_runner.create_file("src/python/foo/bar/__init__.py")
    chroot_rule_runner.create_file("src/python/foo/bar/bar.py")
    # Add a `.pyi` stub file to ensure we include it in the final result.
    chroot_rule_runner.create_file("src/python/foo/bar/bar.pyi")
    chroot_rule_runner.add_to_build_file(
        "src/python/foo/resources", 'resource(source="js/code.js")'
    )
    chroot_rule_runner.create_file("src/python/foo/resources/js/code.js")
    chroot_rule_runner.add_to_build_file("files", 'file(source="README.txt")')
    chroot_rule_runner.create_file("files/README.txt")
    chroot_rule_runner.add_to_build_file(
        "src/python/",
        textwrap.dedent(
            """
            python_distribution(
                name='foo-dist',
                dependencies=[
                    ':setup',
                ],
                generate_setup=False,
                provides=setup_py(
                    name='foo', version='1.2.3',
                )
            )

            python_sources(name="setup", dependencies=["src/python/foo"])
            """
        ),
    )
    chroot_rule_runner.create_file(
        "src/python/setup.py",
        textwrap.dedent(
            """
        from setuptools import setup

        setup(
            name = "foo",
            version = "1.2.3",
            packages = ["foo"],
        )
    """
        ),
    )
    chroot_rule_runner.add_to_build_file(
        "src/python/foo",
        textwrap.dedent(
            """
            python_sources(
                dependencies=[
                    'src/python/foo/bar',
                    'src/python/foo/resources',
                    'files',
                ]
            )
            """
        ),
    )
    chroot_rule_runner.create_file("src/python/foo/__init__.py", _namespace_decl)
    chroot_rule_runner.create_file("src/python/foo/foo.py")
    assert_chroot(
        chroot_rule_runner,
        [
            "setup.py",
            "files/README.txt",
            "foo/bar/__init__.py",
            "foo/bar/bar.py",
            "foo/bar/bar.pyi",
            "foo/resources/js/code.js",
            "foo/__init__.py",
            "foo/foo.py",
        ],
        None,
        Address("src/python", target_name="foo-dist"),
    )


def test_merge_entry_points() -> None:
    sources = {
        "src/python/foo:foo-dist `entry_points`": {
            "console_scripts": {"foo_tool": "foo.bar.baz:Tool.main"},
            "foo_plugins": {"qux": "foo.qux"},
        },
        "src/python/foo:foo-dist `provides.entry_points`": {
            "console_scripts": {"foo_qux": "foo.baz.qux"},
            "foo_plugins": {"foo-bar": "foo.bar:plugin"},
        },
    }
    expect = {
        "console_scripts": {
            "foo_tool": "foo.bar.baz:Tool.main",
            "foo_qux": "foo.baz.qux",
        },
        "foo_plugins": {
            "qux": "foo.qux",
            "foo-bar": "foo.bar:plugin",
        },
    }
    assert merge_entry_points(*list(sources.items())) == expect

    conflicting_sources = {
        "src/python/foo:foo-dist `entry_points`": {"console_scripts": {"my-tool": "ep1"}},
        "src/python/foo:foo-dist `provides.entry_points`": {"console_scripts": {"my-tool": "ep2"}},
    }

    err_msg = (
        "Multiple entry_points registered for console_scripts my-tool in: "
        "src/python/foo:foo-dist `entry_points`, "
        "src/python/foo:foo-dist `provides.entry_points`"
    )
    with pytest.raises(ValueError, match=err_msg):
        merge_entry_points(*list(conflicting_sources.items()))


def test_generate_chroot(chroot_rule_runner: RuleRunner) -> None:
    chroot_rule_runner.add_to_build_file(
        "src/python/foo/bar/baz",
        textwrap.dedent(
            """
            python_distribution(
                name="baz-dist",
                dependencies=[':baz'],
                provides=setup_py(
                    name='baz',
                    version='1.1.1'
                )
            )

            python_sources()
            """
        ),
    )
    chroot_rule_runner.create_file("src/python/foo/bar/baz/baz.py")
    chroot_rule_runner.add_to_build_file(
        "src/python/foo/qux",
        textwrap.dedent(
            """
            python_sources()

            pex_binary(name="bin", entry_point="foo.qux.bin:main")
            """
        ),
    )
    chroot_rule_runner.create_file("src/python/foo/qux/__init__.py")
    chroot_rule_runner.create_file("src/python/foo/qux/qux.py")
    # Add a `.pyi` stub file to ensure we include it in the final result.
    chroot_rule_runner.create_file("src/python/foo/qux/qux.pyi")
    chroot_rule_runner.add_to_build_file(
        "src/python/foo/resources", 'resource(source="js/code.js")'
    )
    chroot_rule_runner.create_file("src/python/foo/resources/js/code.js")
    chroot_rule_runner.add_to_build_file("files", 'file(source="README.txt")')
    chroot_rule_runner.create_file("files/README.txt")
    chroot_rule_runner.add_to_build_file(
        "src/python/foo",
        textwrap.dedent(
            """
            python_distribution(
                name='foo-dist',
                dependencies=[
                    ':foo',
                ],
                provides=setup_py(
                    name='foo', version='1.2.3'
                ),
                entry_points={
                    "console_scripts":{
                        "foo_main": "src/python/foo/qux:bin",
                    },
                },
            )

            python_sources(
                dependencies=[
                    'src/python/foo/bar/baz',
                    'src/python/foo/qux',
                    'src/python/foo/resources',
                    'files',
                ]
            )
            """
        ),
    )
    chroot_rule_runner.create_file("src/python/foo/__init__.py", _namespace_decl)
    chroot_rule_runner.create_file("src/python/foo/foo.py")
    assert_chroot(
        chroot_rule_runner,
        [
            "files/README.txt",
            "foo/qux/__init__.py",
            "foo/qux/qux.py",
            "foo/qux/qux.pyi",
            "foo/resources/js/code.js",
            "foo/__init__.py",
            "foo/foo.py",
            "setup.py",
            "MANIFEST.in",
        ],
        {
            "name": "foo",
            "version": "1.2.3",
            "plugin_demo": "hello world",
            "packages": ("foo", "foo.qux"),
            "namespace_packages": ("foo",),
            "package_data": {"foo": ("resources/js/code.js",), "foo.qux": ("qux.pyi",)},
            "install_requires": ("baz==1.1.1",),
            "entry_points": {"console_scripts": ["foo_main = foo.qux.bin:main"]},
        },
        Address("src/python/foo", target_name="foo-dist"),
    )


def test_generate_chroot_entry_points(chroot_rule_runner: RuleRunner) -> None:
    chroot_rule_runner.add_to_build_file(
        "src/python/foo/qux",
        textwrap.dedent(
            """
            python_sources()

            pex_binary(name="bin", entry_point="foo.qux.bin:main")
            """
        ),
    )
    chroot_rule_runner.add_to_build_file(
        "src/python/foo",
        textwrap.dedent(
            """
            python_distribution(
                name='foo-dist',
                entry_points={
                    "console_scripts":{
                        "foo_main": "src/python/foo/qux:bin",
                        "foo_tool":"foo.bar.baz:Tool.main",
                        "bin_tool":"//src/python/foo/qux:bin",
                        "bin_tool2":"src/python/foo/qux:bin",
                        "hello":":foo-bin",
                    },
                    "foo_plugins":{
                        "qux":"foo.qux",
                    },
                },
                provides=setup_py(
                    name='foo', version='1.2.3',
                    entry_points={
                        "console_scripts":{
                            "foo_qux":"foo.baz.qux:main",
                            "foo_bin":":foo-bin",
                        },
                        "foo_plugins":[
                            "foo-bar=foo.bar:plugin",
                        ],
                    },
                )
            )

            python_sources(
                dependencies=[
                    'src/python/foo/qux',
                ]
            )

            pex_binary(name="foo-bin", entry_point="foo.bin:main")
            """
        ),
    )
    assert_chroot(
        chroot_rule_runner,
        [
            "setup.py",
            "MANIFEST.in",
        ],
        {
            "name": "foo",
            "version": "1.2.3",
            "plugin_demo": "hello world",
            "packages": tuple(),
            "namespace_packages": tuple(),
            "package_data": {},
            "install_requires": tuple(),
            "entry_points": {
                "console_scripts": [
                    "foo_main = foo.qux.bin:main",
                    "foo_tool = foo.bar.baz:Tool.main",
                    "bin_tool = foo.qux.bin:main",
                    "bin_tool2 = foo.qux.bin:main",
                    "hello = foo.bin:main",
                    "foo_qux = foo.baz.qux:main",
                    "foo_bin = foo.bin:main",
                ],
                "foo_plugins": [
                    "qux = foo.qux",
                    "foo-bar = foo.bar:plugin",
                ],
            },
        },
        Address("src/python/foo", target_name="foo-dist"),
    )


def test_invalid_binary(chroot_rule_runner: RuleRunner) -> None:
    chroot_rule_runner.create_files("src/python/invalid_binary", ["app1.py", "app2.py"])
    chroot_rule_runner.add_to_build_file(
        "src/python/invalid_binary",
        textwrap.dedent(
            """
            python_sources(name='not_a_binary', sources=[])
            pex_binary(name='invalid_entrypoint_unowned1', entry_point='app1.py')
            pex_binary(name='invalid_entrypoint_unowned2', entry_point='invalid_binary.app2')
            python_distribution(
                name='invalid_bin1',
                provides=setup_py(
                    name='invalid_bin1', version='1.1.1'
                ),
                entry_points={
                    "console_scripts":{
                        "foo": ":not_a_binary",
                    },
                },
            )
            python_distribution(
                name='invalid_bin2',
                provides=setup_py(
                    name='invalid_bin2', version='1.1.1'
                ),
                entry_points={
                    "console_scripts":{
                        "foo": ":invalid_entrypoint_unowned1",
                    },
                },
            )
            python_distribution(
                name='invalid_bin3',
                provides=setup_py(
                    name='invalid_bin3', version='1.1.1'
                ),
                entry_points={
                    "console_scripts":{
                        "foo": ":invalid_entrypoint_unowned2",
                    },
                },
            )
            """
        ),
    )

    assert_chroot_error(
        chroot_rule_runner,
        Address("src/python/invalid_binary", target_name="invalid_bin1"),
        InvalidEntryPoint,
    )
    assert_chroot_error(
        chroot_rule_runner,
        Address("src/python/invalid_binary", target_name="invalid_bin2"),
        InvalidEntryPoint,
    )
    assert_chroot_error(
        chroot_rule_runner,
        Address("src/python/invalid_binary", target_name="invalid_bin3"),
        InvalidEntryPoint,
    )


def test_binary_shorthand(chroot_rule_runner: RuleRunner) -> None:
    chroot_rule_runner.create_file("src/python/project/app.py")
    chroot_rule_runner.add_to_build_file(
        "src/python/project",
        textwrap.dedent(
            """
            python_sources()
            pex_binary(name='bin', entry_point='app.py:func')
            python_distribution(
                name='dist',
                provides=setup_py(
                    name='bin', version='1.1.1'
                ),
                entry_points={
                    "console_scripts":{
                        "foo": ":bin",
                    },
                },
            )
            """
        ),
    )
    assert_chroot(
        chroot_rule_runner,
        ["project/app.py", "setup.py", "MANIFEST.in"],
        {
            "name": "bin",
            "version": "1.1.1",
            "plugin_demo": "hello world",
            "packages": ("project",),
            "namespace_packages": (),
            "install_requires": (),
            "package_data": {},
            "entry_points": {"console_scripts": ["foo = project.app:func"]},
        },
        Address("src/python/project", target_name="dist"),
    )


def test_get_sources() -> None:
    def assert_sources(
        expected_files,
        expected_packages,
        expected_namespace_packages,
        expected_package_data,
        addrs,
    ):
        rule_runner = create_setup_py_rule_runner(
            rules=[
                get_sources,
                get_owned_dependencies,
                get_exporting_owner,
                *target_types_rules.rules(),
                *python_sources.rules(),
                QueryRule(OwnedDependencies, (DependencyOwner,)),
                QueryRule(DistBuildSources, (DistBuildChrootRequest,)),
            ]
        )

        rule_runner.add_to_build_file(
            "src/python/foo/bar/baz",
            textwrap.dedent(
                """
                python_sources(name='baz1', sources=['baz1.py'])
                python_sources(name='baz2', sources=['baz2.py'])
                """
            ),
        )
        rule_runner.create_file("src/python/foo/bar/baz/baz1.py")
        rule_runner.create_file("src/python/foo/bar/baz/baz2.py")
        rule_runner.create_file("src/python/foo/bar/__init__.py", _namespace_decl)
        rule_runner.add_to_build_file("src/python/foo/qux", "python_sources()")
        rule_runner.create_file("src/python/foo/qux/__init__.py")
        rule_runner.create_file("src/python/foo/qux/qux.py")
        rule_runner.add_to_build_file("src/python/foo/resources", 'resource(source="js/code.js")')
        rule_runner.create_file("src/python/foo/resources/js/code.js")
        rule_runner.create_file("src/python/foo/__init__.py")

        # We synthesize an owner for the addrs, so we have something to put in SetupPyChrootRequest.
        rule_runner.create_file(
            "src/python/foo/BUILD",
            textwrap.dedent(
                f"""
                python_distribution(
                  name="dist",
                  dependencies=["{'","'.join(addr.spec for addr in addrs)}"],
                  provides=setup_py(name="foo", version="3.2.1"),
                )
            """
            ),
        )
        owner_tgt = rule_runner.get_target(Address("src/python/foo", target_name="dist"))
        srcs = rule_runner.request(
            DistBuildSources,
            [DistBuildChrootRequest(ExportedTarget(owner_tgt), py2=False)],
        )
        chroot_snapshot = rule_runner.request(Snapshot, [srcs.digest])

        assert sorted(expected_files) == sorted(chroot_snapshot.files)
        assert sorted(expected_packages) == sorted(srcs.packages)
        assert sorted(expected_namespace_packages) == sorted(srcs.namespace_packages)
        assert expected_package_data == dict(srcs.package_data)

    assert_sources(
        expected_files=["foo/bar/baz/baz1.py", "foo/bar/__init__.py", "foo/__init__.py"],
        expected_packages=["foo", "foo.bar", "foo.bar.baz"],
        expected_namespace_packages=["foo.bar"],
        expected_package_data={},
        addrs=[Address("src/python/foo/bar/baz", target_name="baz1")],
    )

    assert_sources(
        expected_files=["foo/bar/baz/baz2.py", "foo/bar/__init__.py", "foo/__init__.py"],
        expected_packages=["foo", "foo.bar", "foo.bar.baz"],
        expected_namespace_packages=["foo.bar"],
        expected_package_data={},
        addrs=[Address("src/python/foo/bar/baz", target_name="baz2")],
    )

    assert_sources(
        expected_files=["foo/qux/qux.py", "foo/qux/__init__.py", "foo/__init__.py"],
        expected_packages=["foo", "foo.qux"],
        expected_namespace_packages=[],
        expected_package_data={},
        addrs=[Address("src/python/foo/qux")],
    )

    assert_sources(
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
        addrs=[
            Address("src/python/foo/bar/baz", target_name="baz1"),
            Address("src/python/foo/qux"),
            Address("src/python/foo/resources"),
        ],
    )

    assert_sources(
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
            Address("src/python/foo/bar/baz", target_name="baz1"),
            Address("src/python/foo/bar/baz", target_name="baz2"),
            Address("src/python/foo/qux"),
            Address("src/python/foo/resources"),
        ],
    )


def test_get_requirements() -> None:
    rule_runner = create_setup_py_rule_runner(
        rules=[
            determine_setup_kwargs,
            get_requirements,
            get_owned_dependencies,
            get_exporting_owner,
            SubsystemRule(SetupPyGeneration),
            QueryRule(ExportedTargetRequirements, (DependencyOwner,)),
        ]
    )
    rule_runner.add_to_build_file(
        "3rdparty",
        textwrap.dedent(
            """
            python_requirement(name='ext1', requirements=['ext1==1.22.333'])
            python_requirement(name='ext2', requirements=['ext2==4.5.6'])
            python_requirement(name='ext3', requirements=['ext3==0.0.1'])
            """
        ),
    )
    rule_runner.add_to_build_file(
        "src/python/foo/bar/baz",
        "python_sources(dependencies=['3rdparty:ext1'], sources=[])",
    )
    rule_runner.add_to_build_file(
        "src/python/foo/bar/qux",
        "python_sources(dependencies=['3rdparty:ext2', 'src/python/foo/bar/baz'], sources=[])",
    )
    rule_runner.add_to_build_file(
        "src/python/foo/bar",
        textwrap.dedent(
            """
            python_distribution(
                name='bar-dist',
                dependencies=[':bar'],
                provides=setup_py(name='bar', version='9.8.7'),
            )

            python_sources(
                sources=[],
                dependencies=['src/python/foo/bar/baz', 'src/python/foo/bar/qux'],
            )
          """
        ),
    )
    rule_runner.add_to_build_file(
        "src/python/foo/corge",
        textwrap.dedent(
            """
            python_distribution(
                name='corge-dist',
                # Tests having a 3rdparty requirement directly on a python_distribution.
                dependencies=[':corge', '3rdparty:ext3'],
                provides=setup_py(name='corge', version='2.2.2'),
            )

            python_sources(
                sources=[],
                dependencies=['src/python/foo/bar'],
            )
            """
        ),
    )

    assert_requirements(
        rule_runner,
        ["ext1==1.22.333", "ext2==4.5.6"],
        Address("src/python/foo/bar", target_name="bar-dist"),
    )
    assert_requirements(
        rule_runner,
        ["ext3==0.0.1", "bar==9.8.7"],
        Address("src/python/foo/corge", target_name="corge-dist"),
    )

    assert_requirements(
        rule_runner,
        ["ext3==0.0.1", "bar~=9.8.7"],
        Address("src/python/foo/corge", target_name="corge-dist"),
        version_scheme=FirstPartyDependencyVersionScheme.COMPATIBLE,
    )
    assert_requirements(
        rule_runner,
        ["ext3==0.0.1", "bar"],
        Address("src/python/foo/corge", target_name="corge-dist"),
        version_scheme=FirstPartyDependencyVersionScheme.ANY,
    )


def test_get_requirements_with_exclude() -> None:
    rule_runner = create_setup_py_rule_runner(
        rules=[
            determine_setup_kwargs,
            get_requirements,
            get_owned_dependencies,
            get_exporting_owner,
            SubsystemRule(SetupPyGeneration),
            QueryRule(ExportedTargetRequirements, (DependencyOwner,)),
        ]
    )
    rule_runner.add_to_build_file(
        "3rdparty",
        textwrap.dedent(
            """
            python_requirement(name='ext1', requirements=['ext1==1.22.333'])
            python_requirement(name='ext2', requirements=['ext2==4.5.6'])
            python_requirement(name='ext3', requirements=['ext3==0.0.1'])
            """
        ),
    )
    rule_runner.add_to_build_file(
        "src/python/foo/bar/baz",
        "python_sources(dependencies=['3rdparty:ext1'], sources=[])",
    )
    rule_runner.add_to_build_file(
        "src/python/foo/bar/qux",
        "python_sources(dependencies=['3rdparty:ext2', 'src/python/foo/bar/baz'], sources=[])",
    )
    rule_runner.add_to_build_file(
        "src/python/foo/bar",
        textwrap.dedent(
            """
            python_distribution(
                name='bar-dist',
                dependencies=['!!3rdparty:ext2',':bar'],
                provides=setup_py(name='bar', version='9.8.7'),
            )

            python_sources(
                sources=[],
                dependencies=['src/python/foo/bar/baz', 'src/python/foo/bar/qux'],
            )
          """
        ),
    )

    assert_requirements(
        rule_runner, ["ext1==1.22.333"], Address("src/python/foo/bar", target_name="bar-dist")
    )


def assert_requirements(
    rule_runner,
    expected_req_strs,
    addr: Address,
    *,
    version_scheme: FirstPartyDependencyVersionScheme = FirstPartyDependencyVersionScheme.EXACT,
):
    rule_runner.set_options(
        [f"--setup-py-generation-first-party-dependency-version-scheme={version_scheme.value}"],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    tgt = rule_runner.get_target(addr)
    reqs = rule_runner.request(
        ExportedTargetRequirements,
        [DependencyOwner(ExportedTarget(tgt))],
    )
    assert sorted(expected_req_strs) == list(reqs)


def test_owned_dependencies() -> None:
    rule_runner = create_setup_py_rule_runner(
        rules=[
            get_owned_dependencies,
            get_exporting_owner,
            QueryRule(OwnedDependencies, (DependencyOwner,)),
        ]
    )
    rule_runner.add_to_build_file(
        "src/python/foo/bar/baz",
        textwrap.dedent(
            """
            python_sources(name='baz1', sources=[])
            python_sources(name='baz2', sources=[])
            """
        ),
    )
    rule_runner.create_file("src/python/foo/bar/resource.txt")
    rule_runner.add_to_build_file(
        "src/python/foo/bar",
        textwrap.dedent(
            """
            python_distribution(
                name='bar1-dist',
                dependencies=[':bar1'],
                provides=setup_py(name='bar1', version='1.1.1'),
            )

            python_sources(
                name='bar1',
                sources=[],
                dependencies=['src/python/foo/bar/baz:baz1'],
            )

            python_sources(
                name='bar2',
                sources=[],
                dependencies=[':bar-resources', 'src/python/foo/bar/baz:baz2'],
            )
            resource(name='bar-resources', source='resource.txt')
            """
        ),
    )
    rule_runner.add_to_build_file(
        "src/python/foo",
        textwrap.dedent(
            """
            python_distribution(
                name='foo-dist',
                dependencies=[':foo'],
                provides=setup_py(name='foo', version='3.4.5'),
            )

            python_sources(
                sources=[],
                dependencies=['src/python/foo/bar:bar1', 'src/python/foo/bar:bar2'],
            )
            """
        ),
    )

    def assert_owned(owned: Iterable[str], exported: Address):
        tgt = rule_runner.get_target(exported)
        assert sorted(owned) == sorted(
            od.target.address.spec
            for od in rule_runner.request(
                OwnedDependencies,
                [DependencyOwner(ExportedTarget(tgt))],
            )
        )

    assert_owned(
        ["src/python/foo/bar:bar1", "src/python/foo/bar:bar1-dist", "src/python/foo/bar/baz:baz1"],
        Address("src/python/foo/bar", target_name="bar1-dist"),
    )
    assert_owned(
        [
            "src/python/foo:foo",
            "src/python/foo:foo-dist",
            "src/python/foo/bar:bar2",
            "src/python/foo/bar:bar-resources",
            "src/python/foo/bar/baz:baz2",
        ],
        Address("src/python/foo", target_name="foo-dist"),
    )


@pytest.fixture
def exporting_owner_rule_runner() -> RuleRunner:
    return create_setup_py_rule_runner(
        rules=[
            get_exporting_owner,
            QueryRule(ExportedTarget, (OwnedDependency,)),
        ]
    )


def assert_is_owner(rule_runner: RuleRunner, owner: str, owned: Address):
    tgt = rule_runner.get_target(owned)
    assert (
        owner
        == rule_runner.request(
            ExportedTarget,
            [OwnedDependency(tgt)],
        ).target.address.spec
    )


def assert_owner_error(rule_runner, owned: Address, exc_cls: type[Exception]):
    tgt = rule_runner.get_target(owned)
    with pytest.raises(ExecutionError) as excinfo:
        rule_runner.request(
            ExportedTarget,
            [OwnedDependency(tgt)],
        )
    ex = excinfo.value
    assert len(ex.wrapped_exceptions) == 1
    assert type(ex.wrapped_exceptions[0]) == exc_cls


def assert_no_owner(rule_runner: RuleRunner, owned: Address):
    assert_owner_error(rule_runner, owned, NoOwnerError)


def assert_ambiguous_owner(rule_runner: RuleRunner, owned: Address):
    assert_owner_error(rule_runner, owned, AmbiguousOwnerError)


def test_get_owner_simple(exporting_owner_rule_runner: RuleRunner) -> None:
    exporting_owner_rule_runner.add_to_build_file(
        "src/python/foo/bar/baz",
        textwrap.dedent(
            """
            python_sources(name='baz1', sources=[])
            python_sources(name='baz2', sources=[])
            """
        ),
    )
    exporting_owner_rule_runner.create_file("src/python/foo/bar/resource.ext")
    exporting_owner_rule_runner.add_to_build_file(
        "src/python/foo/bar",
        textwrap.dedent(
            """
            python_distribution(
                name='bar1',
                dependencies=['src/python/foo/bar/baz:baz1'],
                provides=setup_py(name='bar1', version='1.1.1'),
            )
            python_sources(
                name='bar2',
                sources=[],
                dependencies=[':bar-resources', 'src/python/foo/bar/baz:baz2'],
            )
            resource(name='bar-resources', source='resource.ext')
            """
        ),
    )
    exporting_owner_rule_runner.add_to_build_file(
        "src/python/foo",
        textwrap.dedent(
            """
            python_distribution(
                name='foo1',
                dependencies=['src/python/foo/bar/baz:baz2'],
                provides=setup_py(name='foo1', version='0.1.2'),
            )
            python_sources(name='foo2', sources=[])
            python_distribution(
                name='foo3',
                dependencies=['src/python/foo/bar:bar2'],
                provides=setup_py(name='foo3', version='3.4.5'),
            )
            """
        ),
    )

    assert_is_owner(
        exporting_owner_rule_runner,
        "src/python/foo/bar:bar1",
        Address("src/python/foo/bar", target_name="bar1"),
    )
    assert_is_owner(
        exporting_owner_rule_runner,
        "src/python/foo/bar:bar1",
        Address("src/python/foo/bar/baz", target_name="baz1"),
    )

    assert_is_owner(
        exporting_owner_rule_runner,
        "src/python/foo:foo1",
        Address("src/python/foo", target_name="foo1"),
    )

    assert_is_owner(
        exporting_owner_rule_runner,
        "src/python/foo:foo3",
        Address("src/python/foo", target_name="foo3"),
    )
    assert_is_owner(
        exporting_owner_rule_runner,
        "src/python/foo:foo3",
        Address("src/python/foo/bar", target_name="bar2"),
    )
    assert_is_owner(
        exporting_owner_rule_runner,
        "src/python/foo:foo3",
        Address("src/python/foo/bar", target_name="bar-resources"),
    )

    assert_no_owner(exporting_owner_rule_runner, Address("src/python/foo", target_name="foo2"))
    assert_ambiguous_owner(
        exporting_owner_rule_runner, Address("src/python/foo/bar/baz", target_name="baz2")
    )


def test_get_owner_siblings(exporting_owner_rule_runner: RuleRunner) -> None:
    exporting_owner_rule_runner.add_to_build_file(
        "src/python/siblings",
        textwrap.dedent(
            """
            python_sources(name='sibling1', sources=[])
            python_distribution(
                name='sibling2',
                dependencies=['src/python/siblings:sibling1'],
                provides=setup_py(name='siblings', version='2.2.2'),
            )
            """
        ),
    )

    assert_is_owner(
        exporting_owner_rule_runner,
        "src/python/siblings:sibling2",
        Address("src/python/siblings", target_name="sibling1"),
    )
    assert_is_owner(
        exporting_owner_rule_runner,
        "src/python/siblings:sibling2",
        Address("src/python/siblings", target_name="sibling2"),
    )


def test_get_owner_not_an_ancestor(exporting_owner_rule_runner: RuleRunner) -> None:
    exporting_owner_rule_runner.add_to_build_file(
        "src/python/notanancestor/aaa",
        textwrap.dedent(
            """
            python_sources(name='aaa', sources=[])
            """
        ),
    )
    exporting_owner_rule_runner.add_to_build_file(
        "src/python/notanancestor/bbb",
        textwrap.dedent(
            """
            python_distribution(
                name='bbb',
                dependencies=['src/python/notanancestor/aaa'],
                provides=setup_py(name='bbb', version='11.22.33'),
            )
            """
        ),
    )

    assert_no_owner(exporting_owner_rule_runner, Address("src/python/notanancestor/aaa"))
    assert_is_owner(
        exporting_owner_rule_runner,
        "src/python/notanancestor/bbb:bbb",
        Address("src/python/notanancestor/bbb"),
    )


def test_get_owner_multiple_ancestor_generations(exporting_owner_rule_runner: RuleRunner) -> None:
    exporting_owner_rule_runner.add_to_build_file(
        "src/python/aaa/bbb/ccc",
        textwrap.dedent(
            """
            python_sources(name='ccc', sources=[])
            """
        ),
    )
    exporting_owner_rule_runner.add_to_build_file(
        "src/python/aaa/bbb",
        textwrap.dedent(
            """
            python_distribution(
                name='bbb',
                dependencies=['src/python/aaa/bbb/ccc'],
                provides=setup_py(name='bbb', version='1.1.1'),
            )
            """
        ),
    )
    exporting_owner_rule_runner.add_to_build_file(
        "src/python/aaa",
        textwrap.dedent(
            """
            python_distribution(
                name='aaa',
                dependencies=['src/python/aaa/bbb/ccc'],
                provides=setup_py(name='aaa', version='2.2.2'),
            )
            """
        ),
    )

    assert_is_owner(
        exporting_owner_rule_runner, "src/python/aaa/bbb:bbb", Address("src/python/aaa/bbb/ccc")
    )
    assert_is_owner(
        exporting_owner_rule_runner, "src/python/aaa/bbb:bbb", Address("src/python/aaa/bbb")
    )
    assert_is_owner(exporting_owner_rule_runner, "src/python/aaa:aaa", Address("src/python/aaa"))


def test_validate_args() -> None:
    with pytest.raises(InvalidSetupPyArgs):
        validate_commands(("bdist_wheel", "upload"))
    with pytest.raises(InvalidSetupPyArgs):
        validate_commands(("sdist", "-d", "new_distdir/"))
    with pytest.raises(InvalidSetupPyArgs):
        validate_commands(("--dist-dir", "new_distdir/", "sdist"))

    validate_commands(("sdist",))
    validate_commands(("bdist_wheel", "--foo"))


@pytest.mark.parametrize(
    "python_src",
    [
        "__import__('pkg_resources').declare_namespace(__name__)",
        "\n__import__('pkg_resources').declare_namespace(__name__)  # type: ignore[attr-defined]",
        "import pkg_resources; pkg_resources.declare_namespace(__name__)",
        "from pkg_resources import declare_namespace; declare_namespace(__name__)",
    ],
)
def test_declares_pkg_resources_namespace_package(python_src: str) -> None:
    assert declares_pkg_resources_namespace_package(python_src)


@pytest.mark.parametrize(
    "python_src",
    [
        "",
        "import os\n\nos.getcwd()",
        "__path__ = 'foo'",
        "import pkg_resources",
        "add(1, 2); foo(__name__); self.shoot(__name__)",
        "declare_namespace(bonk)",
        "just nonsense, not even parseable",
    ],
)
def test_does_not_declare_pkg_resources_namespace_package(python_src: str) -> None:
    assert not declares_pkg_resources_namespace_package(python_src)
