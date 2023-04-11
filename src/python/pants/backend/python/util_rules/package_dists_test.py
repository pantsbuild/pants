# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import textwrap
from typing import Iterable

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.goals.package_dists import package_python_dist
from pants.backend.python.macros.python_artifact import PythonArtifact
from pants.backend.python.subsystems.setup_py_generation import (
    FirstPartyDependencyVersionScheme,
    SetupPyGeneration,
)
from pants.backend.python.subsystems.setuptools import PythonDistributionFieldSet
from pants.backend.python.target_types import (
    PexBinary,
    PythonDistribution,
    PythonProvidesField,
    PythonRequirementTarget,
    PythonSourcesGeneratorTarget,
)
from pants.backend.python.util_rules import dists, python_sources
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.package_dists import (
    AmbiguousOwnerError,
    DependencyOwner,
    DistBuildChroot,
    DistBuildChrootRequest,
    DistBuildSources,
    ExportedTarget,
    ExportedTargetRequirements,
    FinalizedSetupKwargs,
    GenerateSetupPyRequest,
    InvalidEntryPoint,
    InvalidSetupPyArgs,
    NoDistTypeSelected,
    NoOwnerError,
    OwnedDependencies,
    OwnedDependency,
    SetupKwargs,
    SetupKwargsRequest,
    SetupPyError,
    declares_pkg_resources_namespace_package,
    determine_explicitly_provided_setup_kwargs,
    determine_finalized_setup_kwargs,
    generate_chroot,
    generate_setup_py,
    get_exporting_owner,
    get_owned_dependencies,
    get_requirements,
    get_sources,
    merge_entry_points,
    validate_commands,
)
from pants.base.exceptions import IntrinsicError
from pants.core.goals.package import BuiltPackage
from pants.core.target_types import FileTarget, ResourcesGeneratorTarget, ResourceTarget
from pants.core.target_types import rules as core_target_types_rules
from pants.engine.addresses import Address
from pants.engine.fs import Snapshot
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.rules import rule
from pants.engine.target import InvalidFieldException
from pants.engine.unions import UnionRule
from pants.testutil.python_rule_runner import PythonRuleRunner
from pants.testutil.rule_runner import QueryRule, engine_error
from pants.util.strutil import softwrap

_namespace_decl = "__import__('pkg_resources').declare_namespace(__name__)"


def create_setup_py_rule_runner(*, rules: Iterable) -> PythonRuleRunner:
    rule_runner = PythonRuleRunner(
        rules=rules,
        target_types=[
            PexBinary,
            PythonDistribution,
            PythonSourcesGeneratorTarget,
            PythonRequirementTarget,
            ResourceTarget,
            ResourcesGeneratorTarget,
            FileTarget,
        ],
        objects={"python_artifact": PythonArtifact},
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
    kwargs = {**request.explicit_kwargs, "plugin_demo": "hello world"}
    return SetupKwargs(kwargs, address=request.target.address)


@pytest.fixture
def chroot_rule_runner() -> PythonRuleRunner:
    return create_setup_py_rule_runner(
        rules=[
            *core_target_types_rules(),
            determine_explicitly_provided_setup_kwargs,
            generate_chroot,
            generate_setup_py,
            determine_finalized_setup_kwargs,
            get_sources,
            get_requirements,
            get_owned_dependencies,
            get_exporting_owner,
            *python_sources.rules(),
            *target_types_rules.rules(),
            setup_kwargs_plugin,
            *SetupPyGeneration.rules(),
            UnionRule(SetupKwargsRequest, PluginSetupKwargsRequest),
            QueryRule(DistBuildChroot, (DistBuildChrootRequest,)),
            QueryRule(DistBuildSources, (DistBuildChrootRequest,)),
            QueryRule(FinalizedSetupKwargs, (GenerateSetupPyRequest,)),
        ]
    )


def assert_chroot(
    rule_runner: PythonRuleRunner,
    expected_files: list[str],
    expected_setup_kwargs,
    addr: Address,
    interpreter_constraints: InterpreterConstraints | None = None,
) -> None:
    if interpreter_constraints is None:
        interpreter_constraints = InterpreterConstraints(["CPython>=3.7,<4"])

    tgt = rule_runner.get_target(addr)
    req = DistBuildChrootRequest(
        ExportedTarget(tgt), interpreter_constraints=interpreter_constraints
    )
    chroot = rule_runner.request(DistBuildChroot, [req])
    snapshot = rule_runner.request(Snapshot, [chroot.digest])
    assert sorted(expected_files) == sorted(snapshot.files)

    if expected_setup_kwargs is not None:
        sources = rule_runner.request(DistBuildSources, [req])
        setup_kwargs = rule_runner.request(
            FinalizedSetupKwargs,
            [GenerateSetupPyRequest(ExportedTarget(tgt), sources, interpreter_constraints)],
        )
        assert expected_setup_kwargs == setup_kwargs.kwargs


def assert_chroot_error(
    rule_runner: PythonRuleRunner, addr: Address, exc_cls: type[Exception]
) -> None:
    tgt = rule_runner.get_target(addr)
    with pytest.raises(ExecutionError) as excinfo:
        rule_runner.request(
            DistBuildChroot,
            [
                DistBuildChrootRequest(
                    ExportedTarget(tgt),
                    InterpreterConstraints(["CPython>=3.7,<4"]),
                )
            ],
        )
    ex = excinfo.value
    assert len(ex.wrapped_exceptions) == 1
    assert type(ex.wrapped_exceptions[0]) == exc_cls


def test_use_existing_setup_script(chroot_rule_runner) -> None:
    chroot_rule_runner.write_files(
        {
            "src/python/foo/bar/BUILD": "python_sources()",
            "src/python/foo/bar/__init__.py": "",
            "src/python/foo/bar/bar.py": "",
            # Add a `.pyi` stub file to ensure we include it in the final result.
            "src/python/foo/bar/bar.pyi": "",
            "src/python/foo/resources/BUILD": 'resource(source="js/code.js")',
            "src/python/foo/resources/js/code.js": "",
            "files/BUILD": 'file(source="README.txt")',
            "files/README.txt": "",
            "BUILD": textwrap.dedent(
                """
                python_distribution(
                    name='foo-dist',
                    dependencies=[
                        ':setup',
                    ],
                    generate_setup=False,
                    provides=python_artifact(
                        name='foo', version='1.2.3',
                    )
                )

                python_sources(name="setup", dependencies=["src/python/foo"])
                """
            ),
            "setup.py": textwrap.dedent(
                """
                from setuptools import setup

                setup(
                    name = "foo",
                    version = "1.2.3",
                    package_dir={"": "src/python"},
                    packages = ["foo"],
                )
                """
            ),
            "src/python/foo/BUILD": textwrap.dedent(
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
            "src/python/foo/__init__.py": _namespace_decl,
            "src/python/foo/foo.py": "",
        }
    )
    assert_chroot(
        chroot_rule_runner,
        [
            "setup.py",
            "files/README.txt",
            "src/python/foo/bar/__init__.py",
            "src/python/foo/bar/bar.py",
            "src/python/foo/bar/bar.pyi",
            "src/python/foo/resources/js/code.js",
            "src/python/foo/__init__.py",
            "src/python/foo/foo.py",
        ],
        None,
        Address("", target_name="foo-dist"),
    )


def test_use_generate_setup_script_package_provenance_agnostic(chroot_rule_runner) -> None:
    chroot_rule_runner.write_files(
        {
            "src/python/foo/BUILD": textwrap.dedent(
                """
                python_sources(
                    dependencies=[
                        'src/python/resources',
                    ]
                )
                """
            ),
            "src/python/foo/bar.py": "",
            # Here we have a Python package of resources.js defined via files owned by a resources
            # target. From a packaging perspective, we should be agnostic to what targets own a
            # python package when calculating package_data, we just need to know which packages are
            # defined by Python files in the distribution.
            "src/python/resources/BUILD": 'resources(sources=["**/*.py", "**/*.js"])',
            "src/python/resources/js/__init__.py": "",
            "src/python/resources/js/code.js": "",
            "src/python/BUILD": textwrap.dedent(
                """
                python_distribution(
                    name='foo-dist',
                    dependencies=[
                        'src/python/foo',
                    ],
                    generate_setup=True,
                    provides=python_artifact(
                        name='foo', version='1.2.3',
                    )
                )
                """
            ),
        }
    )
    assert_chroot(
        chroot_rule_runner,
        [
            "foo/bar.py",
            "resources/js/__init__.py",
            "resources/js/code.js",
            "setup.py",
            "MANIFEST.in",
        ],
        {
            "name": "foo",
            "version": "1.2.3",
            "plugin_demo": "hello world",
            "packages": ("foo", "resources.js"),
            "namespace_packages": (),
            "package_data": {
                "resources.js": (
                    "__init__.py",
                    "code.js",
                )
            },
            "install_requires": (),
            "python_requires": "<4,>=3.7",
        },
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

    err_msg = softwrap(
        """
        Multiple entry_points registered for console_scripts my-tool in:
        src/python/foo:foo-dist `entry_points`,
        src/python/foo:foo-dist `provides.entry_points`
        """
    )
    with pytest.raises(ValueError, match=err_msg):
        merge_entry_points(*list(conflicting_sources.items()))


def test_generate_chroot(chroot_rule_runner: PythonRuleRunner) -> None:
    chroot_rule_runner.write_files(
        {
            "src/python/foo/bar/baz/BUILD": textwrap.dedent(
                """
                python_distribution(
                    name="baz-dist",
                    dependencies=[':baz'],
                    provides=python_artifact(
                        name='baz',
                        version='1.1.1'
                    )
                )

                python_sources()
                """
            ),
            "src/python/foo/bar/baz/baz.py": "",
            "src/python/foo/qux/BUILD": textwrap.dedent(
                """
                python_sources()

                pex_binary(name="bin", entry_point="foo.qux.bin:main")
                """
            ),
            "src/python/foo/qux/__init__.py": "",
            "src/python/foo/qux/qux.py": "",
            # Add a `.pyi` stub file to ensure we include it in the final result.
            "src/python/foo/qux/qux.pyi": "",
            "src/python/foo/resources/BUILD": 'resource(source="js/code.js")',
            "src/python/foo/resources/js/code.js": "",
            "files/BUILD": 'file(source="README.txt")',
            "files/README.txt": "",
            "src/python/foo/BUILD": textwrap.dedent(
                """
                python_distribution(
                    name='foo-dist',
                    dependencies=[
                        ':foo',
                    ],
                    provides=python_artifact(
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
            "src/python/foo/__init__.py": _namespace_decl,
            "src/python/foo/foo.py": "",
        }
    )
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
            "python_requires": "<4,>=3.7",
            "entry_points": {"console_scripts": ["foo_main = foo.qux.bin:main"]},
        },
        Address("src/python/foo", target_name="foo-dist"),
    )


def test_generate_chroot_entry_points(chroot_rule_runner: PythonRuleRunner) -> None:
    chroot_rule_runner.write_files(
        {
            "src/python/foo/qux/BUILD": textwrap.dedent(
                """
                python_sources()

                pex_binary(name="bin", entry_point="foo.qux.bin:main")
                """
            ),
            "src/python/foo/BUILD": textwrap.dedent(
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
                    provides=python_artifact(
                        name='foo',
                        version='1.2.3',
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
        }
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
            "python_requires": "<4,>=3.7",
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


def test_generate_long_description_field_from_file(chroot_rule_runner: PythonRuleRunner) -> None:
    chroot_rule_runner.write_files(
        {
            "src/python/foo/BUILD": textwrap.dedent(
                """
                python_distribution(
                    name='foo-dist',
                    long_description_path="src/python/foo/readme.md",
                    provides=python_artifact(
                        name='foo',
                        version='1.2.3',
                    )
                )
                """
            ),
            "src/python/foo/readme.md": "Some long description.",
        }
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
            "python_requires": "<4,>=3.7",
            "long_description": "Some long description.",
        },
        Address("src/python/foo", target_name="foo-dist"),
    )


def test_generate_long_description_field_from_file_already_having_it(
    chroot_rule_runner: PythonRuleRunner,
) -> None:
    chroot_rule_runner.write_files(
        {
            "src/python/foo/BUILD": textwrap.dedent(
                """
                python_distribution(
                    name='foo-dist',
                    long_description_path="src/python/foo/readme.md",
                    provides=python_artifact(
                        name='foo',
                        version='1.2.3',
                        long_description="Some long description.",
                    )
                )
                """
            ),
            "src/python/foo/readme.md": "Some long description.",
        }
    )
    assert_chroot_error(
        chroot_rule_runner,
        Address("src/python/foo", target_name="foo-dist"),
        InvalidFieldException,
    )


def test_generate_long_description_field_from_non_existing_file(
    chroot_rule_runner: PythonRuleRunner,
) -> None:
    chroot_rule_runner.write_files(
        {
            "src/python/foo/BUILD": textwrap.dedent(
                """
                python_distribution(
                    name='foo-dist',
                    long_description_path="src/python/foo/readme.md",
                    provides=python_artifact(
                        name='foo',
                        version='1.2.3',
                    )
                )
                """
            ),
        }
    )
    assert_chroot_error(
        chroot_rule_runner,
        Address("src/python/foo", target_name="foo-dist"),
        IntrinsicError,
    )


def test_invalid_binary(chroot_rule_runner: PythonRuleRunner) -> None:
    chroot_rule_runner.write_files(
        {
            "src/python/invalid_binary/lib.py": "",
            "src/python/invalid_binary/app1.py": "",
            "src/python/invalid_binary/app2.py": "",
            "src/python/invalid_binary/BUILD": textwrap.dedent(
                """\
                python_sources(name='not_a_binary', sources=['lib.py'])
                pex_binary(name='invalid_entrypoint_unowned1', entry_point='app1.py')
                pex_binary(name='invalid_entrypoint_unowned2', entry_point='invalid_binary.app2')
                python_distribution(
                    name='invalid_bin1',
                    provides=python_artifact(
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
                    provides=python_artifact(
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
                    provides=python_artifact(
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
        }
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


def test_binary_shorthand(chroot_rule_runner: PythonRuleRunner) -> None:
    chroot_rule_runner.write_files(
        {
            "src/python/project/app.py": "",
            "src/python/project/BUILD": textwrap.dedent(
                """
                python_sources()
                pex_binary(name='bin', entry_point='app.py:func')
                python_distribution(
                    name='dist',
                    provides=python_artifact(
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
        }
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
            "python_requires": "<4,>=3.7",
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

        rule_runner.write_files(
            {
                "src/python/foo/bar/baz/BUILD": textwrap.dedent(
                    """
                    python_sources(name='baz1', sources=['baz1.py'])
                    python_sources(name='baz2', sources=['baz2.py'])
                    """
                ),
                "src/python/foo/bar/baz/baz1.py": "",
                "src/python/foo/bar/baz/baz2.py": "",
                "src/python/foo/bar/__init__.py": _namespace_decl,
                "src/python/foo/qux/BUILD": "python_sources()",
                "src/python/foo/qux/__init__.py": "",
                "src/python/foo/qux/qux.py": "",
                "src/python/foo/resources/BUILD": 'resource(source="js/code.js")',
                "src/python/foo/resources/js/code.js": "",
                "src/python/foo/__init__.py": "",
                # We synthesize an owner for the addrs, so we have something to put in SetupPyChrootRequest.
                "src/python/foo/BUILD": textwrap.dedent(
                    f"""
                    python_distribution(
                      name="dist",
                      dependencies=["{'","'.join(addr.spec for addr in addrs)}"],
                      provides=python_artifact(name="foo", version="3.2.1"),
                    )
                    """
                ),
            }
        )
        owner_tgt = rule_runner.get_target(Address("src/python/foo", target_name="dist"))
        srcs = rule_runner.request(
            DistBuildSources,
            [
                DistBuildChrootRequest(
                    ExportedTarget(owner_tgt),
                    InterpreterConstraints(["CPython>=3.7,<4"]),
                )
            ],
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
            determine_explicitly_provided_setup_kwargs,
            get_requirements,
            get_owned_dependencies,
            get_exporting_owner,
            *target_types_rules.rules(),
            *SetupPyGeneration.rules(),
            QueryRule(ExportedTargetRequirements, (DependencyOwner,)),
        ]
    )
    rule_runner.write_files(
        {
            "3rdparty/BUILD": textwrap.dedent(
                """
                python_requirement(name='ext1', requirements=['ext1==1.22.333'])
                python_requirement(name='ext2', requirements=['ext2==4.5.6'])
                python_requirement(name='ext3', requirements=['ext3==0.0.1'])
                """
            ),
            "src/python/foo/bar/baz/a.py": "",
            "src/python/foo/bar/baz/BUILD": "python_sources(dependencies=['3rdparty:ext1'])",
            "src/python/foo/bar/qux/a.py": "",
            "src/python/foo/bar/qux/BUILD": "python_sources(dependencies=['3rdparty:ext2', 'src/python/foo/bar/baz'])",
            "src/python/foo/bar/a.py": "",
            "src/python/foo/bar/BUILD": textwrap.dedent(
                """
                python_distribution(
                    name='bar-dist',
                    dependencies=[':bar'],
                    provides=python_artifact(name='bar', version='9.8.7'),
                )

                python_sources(dependencies=['src/python/foo/bar/baz', 'src/python/foo/bar/qux'])
              """
            ),
            "src/python/foo/corge/a.py": "",
            "src/python/foo/corge/BUILD": textwrap.dedent(
                """
                python_distribution(
                    name='corge-dist',
                    # Tests having a 3rdparty requirement directly on a python_distribution.
                    dependencies=[':corge', '3rdparty:ext3'],
                    provides=python_artifact(name='corge', version='2.2.2'),
                )

                python_sources(dependencies=['src/python/foo/bar'])
                """
            ),
        }
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
            determine_explicitly_provided_setup_kwargs,
            get_requirements,
            get_owned_dependencies,
            get_exporting_owner,
            *target_types_rules.rules(),
            *SetupPyGeneration.rules(),
            QueryRule(ExportedTargetRequirements, (DependencyOwner,)),
        ]
    )
    rule_runner.write_files(
        {
            "3rdparty/BUILD": textwrap.dedent(
                """
                python_requirement(name='ext1', requirements=['ext1==1.22.333'])
                python_requirement(name='ext2', requirements=['ext2==4.5.6'])
                python_requirement(name='ext3', requirements=['ext3==0.0.1'])
                """
            ),
            "src/python/foo/bar/baz/a.py": "",
            "src/python/foo/bar/baz/BUILD": "python_sources(dependencies=['3rdparty:ext1'])",
            "src/python/foo/bar/qux/a.py": "",
            "src/python/foo/bar/qux/BUILD": "python_sources(dependencies=['3rdparty:ext2', 'src/python/foo/bar/baz'])",
            "src/python/foo/bar/a.py": "",
            "src/python/foo/bar/BUILD": textwrap.dedent(
                """
                python_distribution(
                    name='bar-dist',
                    dependencies=['!!3rdparty:ext2',':bar'],
                    provides=python_artifact(name='bar', version='9.8.7'),
                )

                python_sources(dependencies=['src/python/foo/bar/baz', 'src/python/foo/bar/qux'])
              """
            ),
        }
    )

    assert_requirements(
        rule_runner, ["ext1==1.22.333"], Address("src/python/foo/bar", target_name="bar-dist")
    )


def test_get_requirements_with_override_dependency_issue_17593() -> None:
    rule_runner = create_setup_py_rule_runner(
        rules=[
            determine_explicitly_provided_setup_kwargs,
            get_requirements,
            get_owned_dependencies,
            get_exporting_owner,
            *target_types_rules.rules(),
            *SetupPyGeneration.rules(),
            QueryRule(ExportedTargetRequirements, (DependencyOwner,)),
        ]
    )
    rule_runner.write_files(
        {
            "3rdparty/BUILD": textwrap.dedent(
                """
                python_requirement(name='ext1', requirements=['ext1==1.22.333'], dependencies=[':ext2'])
                python_requirement(name='ext2', requirements=['ext2==4.5.6'])
                """
            ),
            "src/python/foo/bar/baz/a.py": "",
            "src/python/foo/bar/baz/BUILD": "python_sources(dependencies=['3rdparty:ext1'])",
            "src/python/foo/bar/a.py": "",
            "src/python/foo/bar/BUILD": textwrap.dedent(
                """
                python_distribution(
                    name='bar-dist',
                    dependencies=[':bar'],
                    provides=python_artifact(name='bar', version='9.8.7'),
                )

                python_sources(dependencies=['src/python/foo/bar/baz'])
              """
            ),
        }
    )

    assert_requirements(
        rule_runner,
        ["ext1==1.22.333", "ext2==4.5.6"],
        Address("src/python/foo/bar", target_name="bar-dist"),
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
            *target_types_rules.rules(),
            QueryRule(OwnedDependencies, (DependencyOwner,)),
        ]
    )
    rule_runner.write_files(
        {
            "src/python/foo/bar/baz/BUILD": textwrap.dedent(
                """
                python_sources(name='baz1')
                python_sources(name='baz2')
                """
            ),
            "src/python/foo/bar/resource.txt": "",
            "src/python/foo/bar/bar1.py": "",
            "src/python/foo/bar/bar2.py": "",
            "src/python/foo/bar/BUILD": textwrap.dedent(
                """
                python_distribution(
                    name='bar1-dist',
                    dependencies=[':bar1'],
                    provides=python_artifact(name='bar1', version='1.1.1'),
                )

                python_sources(
                    name='bar1',
                    sources=['bar1.py'],
                    dependencies=['src/python/foo/bar/baz:baz1'],
                )

                python_sources(
                    name='bar2',
                    sources=['bar2.py'],
                    dependencies=[':bar-resources', 'src/python/foo/bar/baz:baz2'],
                )
                resource(name='bar-resources', source='resource.txt')
                """
            ),
            "src/python/foo/foo.py": "",
            "src/python/foo/BUILD": textwrap.dedent(
                """
                python_distribution(
                    name='foo-dist',
                    dependencies=[':foo'],
                    provides=python_artifact(name='foo', version='3.4.5'),
                )

                python_sources(
                    sources=['foo.py'],
                    dependencies=['src/python/foo/bar:bar1', 'src/python/foo/bar:bar2'],
                )
                """
            ),
        }
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
        [
            "src/python/foo/bar/bar1.py:bar1",
            "src/python/foo/bar:bar1-dist",
            "src/python/foo/bar/baz:baz1",
        ],
        Address("src/python/foo/bar", target_name="bar1-dist"),
    )
    assert_owned(
        [
            "src/python/foo/bar/bar2.py:bar2",
            "src/python/foo/foo.py",
            "src/python/foo:foo-dist",
            "src/python/foo/bar:bar-resources",
            "src/python/foo/bar/baz:baz2",
        ],
        Address("src/python/foo", target_name="foo-dist"),
    )


@pytest.fixture
def exporting_owner_rule_runner() -> PythonRuleRunner:
    return create_setup_py_rule_runner(
        rules=[
            get_exporting_owner,
            *target_types_rules.rules(),
            QueryRule(ExportedTarget, (OwnedDependency,)),
        ]
    )


def assert_is_owner(rule_runner: PythonRuleRunner, owner: str, owned: Address):
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


def assert_no_owner(rule_runner: PythonRuleRunner, owned: Address):
    assert_owner_error(rule_runner, owned, NoOwnerError)


def assert_ambiguous_owner(rule_runner: PythonRuleRunner, owned: Address):
    assert_owner_error(rule_runner, owned, AmbiguousOwnerError)


def test_get_owner_simple(exporting_owner_rule_runner: PythonRuleRunner) -> None:
    exporting_owner_rule_runner.write_files(
        {
            "src/python/foo/bar/baz/BUILD": textwrap.dedent(
                """
                python_sources(name='baz1')
                python_sources(name='baz2')
                """
            ),
            "src/python/foo/bar/resource.ext": "",
            "src/python/foo/bar/bar2.py": "",
            "src/python/foo/bar/BUILD": textwrap.dedent(
                """
                python_distribution(
                    name='bar1',
                    dependencies=['src/python/foo/bar/baz:baz1'],
                    provides=python_artifact(name='bar1', version='1.1.1'),
                )
                python_sources(
                    name='bar2',
                    dependencies=[':bar-resources', 'src/python/foo/bar/baz:baz2'],
                )
                resource(name='bar-resources', source='resource.ext')
                """
            ),
            "src/python/foo/foo2.py": "",
            "src/python/foo/BUILD": textwrap.dedent(
                """
                python_distribution(
                    name='foo1',
                    dependencies=['src/python/foo/bar/baz:baz2'],
                    provides=python_artifact(name='foo1', version='0.1.2'),
                )
                python_sources(name='foo2')
                python_distribution(
                    name='foo3',
                    dependencies=['src/python/foo/bar:bar2'],
                    provides=python_artifact(name='foo3', version='3.4.5'),
                )
                """
            ),
        }
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
        Address("src/python/foo/bar", target_name="bar2", relative_file_path="bar2.py"),
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


def test_get_owner_siblings(exporting_owner_rule_runner: PythonRuleRunner) -> None:
    exporting_owner_rule_runner.write_files(
        {
            "src/python/siblings/BUILD": textwrap.dedent(
                """
                python_sources(name='sibling1')
                python_distribution(
                    name='sibling2',
                    dependencies=['src/python/siblings:sibling1'],
                    provides=python_artifact(name='siblings', version='2.2.2'),
                )
                """
            ),
        }
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


def test_get_owner_not_an_ancestor(exporting_owner_rule_runner: PythonRuleRunner) -> None:
    exporting_owner_rule_runner.write_files(
        {
            "src/python/notanancestor/aaa/BUILD": textwrap.dedent(
                """
                python_sources(name='aaa')
                """
            ),
            "src/python/notanancestor/bbb/BUILD": textwrap.dedent(
                """
                python_distribution(
                    name='bbb',
                    dependencies=['src/python/notanancestor/aaa'],
                    provides=python_artifact(name='bbb', version='11.22.33'),
                )
                """
            ),
        }
    )

    assert_no_owner(exporting_owner_rule_runner, Address("src/python/notanancestor/aaa"))
    assert_is_owner(
        exporting_owner_rule_runner,
        "src/python/notanancestor/bbb:bbb",
        Address("src/python/notanancestor/bbb"),
    )


def test_get_owner_multiple_ancestor_generations(
    exporting_owner_rule_runner: PythonRuleRunner,
) -> None:
    exporting_owner_rule_runner.write_files(
        {
            "src/python/aaa/bbb/ccc/BUILD": textwrap.dedent(
                """
                python_sources(name='ccc')
                """
            ),
            "src/python/aaa/bbb/BUILD": textwrap.dedent(
                """
                python_distribution(
                    name='bbb',
                    dependencies=['src/python/aaa/bbb/ccc'],
                    provides=python_artifact(name='bbb', version='1.1.1'),
                )
                """
            ),
            "src/python/aaa/BUILD": textwrap.dedent(
                """
                python_distribution(
                    name='aaa',
                    dependencies=['src/python/aaa/bbb/ccc'],
                    provides=python_artifact(name='aaa', version='2.2.2'),
                )
                """
            ),
        }
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


def test_no_dist_type_selected() -> None:
    rule_runner = PythonRuleRunner(
        rules=[
            determine_explicitly_provided_setup_kwargs,
            generate_chroot,
            generate_setup_py,
            determine_finalized_setup_kwargs,
            get_sources,
            get_requirements,
            get_owned_dependencies,
            get_exporting_owner,
            package_python_dist,
            *dists.rules(),
            *python_sources.rules(),
            *target_types_rules.rules(),
            *SetupPyGeneration.rules(),
            QueryRule(BuiltPackage, (PythonDistributionFieldSet,)),
        ],
        target_types=[PythonDistribution],
        objects={"python_artifact": PythonArtifact},
    )
    rule_runner.write_files(
        {
            "src/python/aaa/BUILD": textwrap.dedent(
                """
                python_distribution(
                    name='aaa',
                    provides=python_artifact(name='aaa', version='2.2.2'),
                    wheel=False,
                    sdist=False
                )
                """
            ),
        }
    )
    address = Address("src/python/aaa", target_name="aaa")
    with pytest.raises(ExecutionError) as exc_info:
        rule_runner.request(
            BuiltPackage,
            inputs=[
                PythonDistributionFieldSet(
                    address=address,
                    provides=PythonProvidesField(
                        PythonArtifact(name="aaa", version="2.2.2"), address
                    ),
                )
            ],
        )
    assert 1 == len(exc_info.value.wrapped_exceptions)
    wrapped_exception = exc_info.value.wrapped_exceptions[0]
    assert isinstance(wrapped_exception, NoDistTypeSelected)
    assert (
        "In order to package src/python/aaa:aaa at least one of 'wheel' or 'sdist' must be `True`."
        == str(wrapped_exception)
    )


def test_too_many_interpreter_constraints(chroot_rule_runner: PythonRuleRunner) -> None:
    chroot_rule_runner.write_files(
        {
            "src/python/foo/BUILD": textwrap.dedent(
                """
                python_distribution(
                    name='foo-dist',
                    provides=python_artifact(
                        name='foo',
                        version='1.2.3',
                    )
                )
                """
            ),
        }
    )

    addr = Address("src/python/foo", target_name="foo-dist")
    tgt = chroot_rule_runner.get_target(addr)
    err = softwrap(
        """
        Expected a single interpreter constraint for src/python/foo:foo-dist,
        got: CPython<3,>=2.7 OR CPython<3.10,>=3.8.
        """
    )

    with engine_error(SetupPyError, contains=err):
        chroot_rule_runner.request(
            DistBuildChroot,
            [
                DistBuildChrootRequest(
                    ExportedTarget(tgt),
                    InterpreterConstraints([">=2.7,<3", ">=3.8,<3.10"]),
                )
            ],
        )
