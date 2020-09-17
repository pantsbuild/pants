# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import textwrap
from typing import Iterable, Type

import pytest

from pants.backend.python.goals.setup_py import (
    AmbiguousOwnerError,
    DependencyOwner,
    ExportedTarget,
    ExportedTargetRequirements,
    InvalidEntryPoint,
    InvalidSetupPyArgs,
    NoOwnerError,
    OwnedDependencies,
    OwnedDependency,
    SetupKwargs,
    SetupKwargsRequest,
    SetupPyChroot,
    SetupPyChrootRequest,
    SetupPySources,
    SetupPySourcesRequest,
    declares_pkg_resources_namespace_package,
    determine_setup_kwargs,
    distutils_repr,
    generate_chroot,
    get_exporting_owner,
    get_owned_dependencies,
    get_requirements,
    get_sources,
    validate_args,
)
from pants.backend.python.macros.python_artifact import PythonArtifact
from pants.backend.python.target_types import (
    PythonBinary,
    PythonDistribution,
    PythonLibrary,
    PythonRequirementLibrary,
)
from pants.backend.python.util_rules import python_sources
from pants.core.target_types import Files, Resources
from pants.engine.addresses import Address
from pants.engine.fs import Snapshot
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.rules import rule
from pants.engine.target import Targets
from pants.engine.unions import UnionRule
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.testutil.option_util import create_options_bootstrapper
from pants.testutil.rule_runner import QueryRule, RuleRunner

_namespace_decl = "__import__('pkg_resources').declare_namespace(__name__)"


def create_setup_py_rule_runner(*, rules: Iterable) -> RuleRunner:
    return RuleRunner(
        rules=rules,
        target_types=[
            PythonBinary,
            PythonDistribution,
            PythonLibrary,
            PythonRequirementLibrary,
            Resources,
            Files,
        ],
        objects={"setup_py": PythonArtifact},
    )


# We use a trivial test that our SetupKwargs plugin hook works.
class PluginSetupKwargsRequest(SetupKwargsRequest):
    @classmethod
    def is_applicable(cls, _) -> bool:
        return True


@rule
def setup_kwargs_plugin(request: PluginSetupKwargsRequest) -> SetupKwargs:
    return SetupKwargs(
        {**request.explicit_kwargs, "plugin_demo": "hello world"}, address=request.target.address
    )


@pytest.fixture
def chroot_rule_runner() -> RuleRunner:
    return create_setup_py_rule_runner(
        rules=[
            determine_setup_kwargs,
            generate_chroot,
            get_sources,
            get_requirements,
            get_owned_dependencies,
            get_exporting_owner,
            *python_sources.rules(),
            setup_kwargs_plugin,
            UnionRule(SetupKwargsRequest, PluginSetupKwargsRequest),
            QueryRule(SetupPyChroot, (SetupPyChrootRequest, OptionsBootstrapper)),
        ]
    )


def assert_chroot(
    rule_runner: RuleRunner, expected_files, expected_setup_kwargs, addr: str
) -> None:
    tgt = rule_runner.get_target(Address.parse(addr))
    chroot = rule_runner.request(
        SetupPyChroot,
        [
            SetupPyChrootRequest(ExportedTarget(tgt), py2=False),
            create_options_bootstrapper(),
        ],
    )
    snapshot = rule_runner.request(Snapshot, [chroot.digest])
    assert sorted(expected_files) == sorted(snapshot.files)
    assert expected_setup_kwargs == chroot.setup_kwargs.kwargs


def assert_chroot_error(rule_runner: RuleRunner, addr: str, exc_cls: Type[Exception]) -> None:
    tgt = rule_runner.get_target(Address.parse(addr))
    with pytest.raises(ExecutionError) as excinfo:
        rule_runner.request(
            SetupPyChroot,
            [
                SetupPyChrootRequest(ExportedTarget(tgt), py2=False),
                create_options_bootstrapper(),
            ],
        )
    ex = excinfo.value
    assert len(ex.wrapped_exceptions) == 1
    assert type(ex.wrapped_exceptions[0]) == exc_cls


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

        python_library()
        """
        ),
    )
    chroot_rule_runner.create_file("src/python/foo/bar/baz/baz.py", "")
    chroot_rule_runner.add_to_build_file(
        "src/python/foo/qux",
        textwrap.dedent(
            """
            python_library()

            python_binary(name="bin", entry_point="foo.qux.bin")
            """
        ),
    )
    chroot_rule_runner.create_file("src/python/foo/qux/__init__.py")
    chroot_rule_runner.create_file("src/python/foo/qux/qux.py")
    chroot_rule_runner.add_to_build_file(
        "src/python/foo/resources", 'resources(sources=["js/code.js"])'
    )
    chroot_rule_runner.create_file("src/python/foo/resources/js/code.js")
    chroot_rule_runner.add_to_build_file("files", 'files(sources=["README.txt"])')
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
                ).with_binaries(
                    foo_main='src/python/foo/qux:bin'
                )
            )

            python_library(
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
            "src/files/README.txt",
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
            "plugin_demo": "hello world",
            "package_dir": {"": "src"},
            "packages": ("foo", "foo.qux"),
            "namespace_packages": ("foo",),
            "package_data": {"foo": ("resources/js/code.js",)},
            "install_requires": ("baz==1.1.1",),
            "entry_points": {"console_scripts": ["foo_main=foo.qux.bin"]},
        },
        "src/python/foo:foo-dist",
    )


def test_invalid_binary(chroot_rule_runner: RuleRunner) -> None:
    chroot_rule_runner.add_to_build_file(
        "src/python/invalid_binary",
        textwrap.dedent(
            """
            python_library(name='not_a_binary', sources=[])
            python_binary(name='no_entrypoint')
            python_distribution(
                name='invalid_bin1',
                provides=setup_py(
                    name='invalid_bin1', version='1.1.1'
                ).with_binaries(foo=':not_a_binary')
            )
            python_distribution(
                name='invalid_bin2',
                provides=setup_py(
                    name='invalid_bin2', version='1.1.1'
                ).with_binaries(foo=':no_entrypoint')
            )
            """
        ),
    )

    assert_chroot_error(
        chroot_rule_runner, "src/python/invalid_binary:invalid_bin1", InvalidEntryPoint
    )
    assert_chroot_error(
        chroot_rule_runner, "src/python/invalid_binary:invalid_bin2", InvalidEntryPoint
    )


def test_get_sources() -> None:
    rule_runner = create_setup_py_rule_runner(
        rules=[
            get_sources,
            *python_sources.rules(),
            QueryRule(SetupPySources, (SetupPySourcesRequest, OptionsBootstrapper)),
        ]
    )

    rule_runner.add_to_build_file(
        "src/python/foo/bar/baz",
        textwrap.dedent(
            """
            python_library(name='baz1', sources=['baz1.py'])
            python_library(name='baz2', sources=['baz2.py'])
            """
        ),
    )
    rule_runner.create_file("src/python/foo/bar/baz/baz1.py")
    rule_runner.create_file("src/python/foo/bar/baz/baz2.py")
    rule_runner.create_file("src/python/foo/bar/__init__.py", _namespace_decl)
    rule_runner.add_to_build_file("src/python/foo/qux", "python_library()")
    rule_runner.create_file("src/python/foo/qux/__init__.py")
    rule_runner.create_file("src/python/foo/qux/qux.py")
    rule_runner.add_to_build_file("src/python/foo/resources", 'resources(sources=["js/code.js"])')
    rule_runner.create_file("src/python/foo/resources/js/code.js")
    rule_runner.create_file("src/python/foo/__init__.py")

    def assert_sources(
        expected_files,
        expected_packages,
        expected_namespace_packages,
        expected_package_data,
        addrs,
    ):
        targets = Targets(rule_runner.get_target(Address.parse(addr)) for addr in addrs)
        srcs = rule_runner.request(
            SetupPySources,
            [SetupPySourcesRequest(targets, py2=False), create_options_bootstrapper()],
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
        addrs=["src/python/foo/bar/baz:baz1"],
    )

    assert_sources(
        expected_files=["foo/bar/baz/baz2.py", "foo/bar/__init__.py", "foo/__init__.py"],
        expected_packages=["foo", "foo.bar", "foo.bar.baz"],
        expected_namespace_packages=["foo.bar"],
        expected_package_data={},
        addrs=["src/python/foo/bar/baz:baz2"],
    )

    assert_sources(
        expected_files=["foo/qux/qux.py", "foo/qux/__init__.py", "foo/__init__.py"],
        expected_packages=["foo", "foo.qux"],
        expected_namespace_packages=[],
        expected_package_data={},
        addrs=["src/python/foo/qux"],
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
        addrs=["src/python/foo/bar/baz:baz1", "src/python/foo/qux", "src/python/foo/resources"],
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
            "src/python/foo/bar/baz:baz1",
            "src/python/foo/bar/baz:baz2",
            "src/python/foo/qux",
            "src/python/foo/resources",
        ],
    )


def test_get_requirements() -> None:
    rule_runner = create_setup_py_rule_runner(
        rules=[
            determine_setup_kwargs,
            get_requirements,
            get_owned_dependencies,
            get_exporting_owner,
            QueryRule(ExportedTargetRequirements, (DependencyOwner, OptionsBootstrapper)),
        ]
    )
    rule_runner.add_to_build_file(
        "3rdparty",
        textwrap.dedent(
            """
            python_requirement_library(
                name='ext1',
                requirements=['ext1==1.22.333'],
            )
            python_requirement_library(
                name='ext2',
                requirements=['ext2==4.5.6'],
            )
            python_requirement_library(
                name='ext3',
                requirements=['ext3==0.0.1'],
            )
            """
        ),
    )
    rule_runner.add_to_build_file(
        "src/python/foo/bar/baz",
        "python_library(dependencies=['3rdparty:ext1'], sources=[])",
    )
    rule_runner.add_to_build_file(
        "src/python/foo/bar/qux",
        "python_library(dependencies=['3rdparty:ext2', 'src/python/foo/bar/baz'], sources=[])",
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

            python_library(
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

            python_library(
                sources=[],
                dependencies=['src/python/foo/bar'],
            )
            """
        ),
    )

    def assert_requirements(expected_req_strs, addr):
        tgt = rule_runner.get_target(Address.parse(addr))
        reqs = rule_runner.request(
            ExportedTargetRequirements,
            [DependencyOwner(ExportedTarget(tgt)), create_options_bootstrapper()],
        )
        assert sorted(expected_req_strs) == list(reqs)

    assert_requirements(["ext1==1.22.333", "ext2==4.5.6"], "src/python/foo/bar:bar-dist")
    assert_requirements(["ext3==0.0.1", "bar==9.8.7"], "src/python/foo/corge:corge-dist")


def test_owned_dependencies() -> None:
    rule_runner = create_setup_py_rule_runner(
        rules=[
            get_owned_dependencies,
            get_exporting_owner,
            QueryRule(OwnedDependencies, (DependencyOwner, OptionsBootstrapper)),
        ]
    )
    rule_runner.add_to_build_file(
        "src/python/foo/bar/baz",
        textwrap.dedent(
            """
            python_library(name='baz1', sources=[])
            python_library(name='baz2', sources=[])
            """
        ),
    )
    rule_runner.add_to_build_file(
        "src/python/foo/bar",
        textwrap.dedent(
            """
            python_distribution(
                name='bar1-dist',
                dependencies=[':bar1'],
                provides=setup_py(name='bar1', version='1.1.1'),
            )

            python_library(
                name='bar1',
                sources=[],
                dependencies=['src/python/foo/bar/baz:baz1'],
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
    rule_runner.add_to_build_file(
        "src/python/foo",
        textwrap.dedent(
            """
            python_distribution(
                name='foo-dist',
                dependencies=[':foo'],
                provides=setup_py(name='foo', version='3.4.5'),
            )

            python_library(
                sources=[],
                dependencies=['src/python/foo/bar:bar1', 'src/python/foo/bar:bar2'],
            )
            """
        ),
    )

    def assert_owned(owned: Iterable[str], exported: str):
        tgt = rule_runner.get_target(Address.parse(exported))
        assert sorted(owned) == sorted(
            od.target.address.spec
            for od in rule_runner.request(
                OwnedDependencies,
                [
                    DependencyOwner(ExportedTarget(tgt)),
                    create_options_bootstrapper(),
                ],
            )
        )

    assert_owned(
        ["src/python/foo/bar:bar1", "src/python/foo/bar:bar1-dist", "src/python/foo/bar/baz:baz1"],
        "src/python/foo/bar:bar1-dist",
    )
    assert_owned(
        [
            "src/python/foo",
            "src/python/foo:foo-dist",
            "src/python/foo/bar:bar2",
            "src/python/foo/bar:bar-resources",
            "src/python/foo/bar/baz:baz2",
        ],
        "src/python/foo:foo-dist",
    )


@pytest.fixture
def exporting_owner_rule_runner() -> RuleRunner:
    return create_setup_py_rule_runner(
        rules=[
            get_exporting_owner,
            QueryRule(ExportedTarget, (OwnedDependency, OptionsBootstrapper)),
        ]
    )


def assert_is_owner(rule_runner: RuleRunner, owner: str, owned: str):
    tgt = rule_runner.get_target(Address.parse(owned))
    assert (
        owner
        == rule_runner.request(
            ExportedTarget,
            [OwnedDependency(tgt), create_options_bootstrapper()],
        ).target.address.spec
    )


def assert_owner_error(rule_runner, owned: str, exc_cls: Type[Exception]):
    tgt = rule_runner.get_target(Address.parse(owned))
    with pytest.raises(ExecutionError) as excinfo:
        rule_runner.request(
            ExportedTarget,
            [OwnedDependency(tgt), create_options_bootstrapper()],
        )
    ex = excinfo.value
    assert len(ex.wrapped_exceptions) == 1
    assert type(ex.wrapped_exceptions[0]) == exc_cls


def assert_no_owner(rule_runner: RuleRunner, owned: str):
    assert_owner_error(rule_runner, owned, NoOwnerError)


def assert_ambiguous_owner(rule_runner: RuleRunner, owned: str):
    assert_owner_error(rule_runner, owned, AmbiguousOwnerError)


def test_get_owner_simple(exporting_owner_rule_runner: RuleRunner) -> None:
    exporting_owner_rule_runner.add_to_build_file(
        "src/python/foo/bar/baz",
        textwrap.dedent(
            """
            python_library(name='baz1', sources=[])
            python_library(name='baz2', sources=[])
            """
        ),
    )
    exporting_owner_rule_runner.add_to_build_file(
        "src/python/foo/bar",
        textwrap.dedent(
            """
            python_distribution(
                name='bar1',
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
    exporting_owner_rule_runner.add_to_build_file(
        "src/python/foo",
        textwrap.dedent(
            """
            python_distribution(
                name='foo1',
                dependencies=['src/python/foo/bar/baz:baz2'],
                provides=setup_py(name='foo1', version='0.1.2'),
            )
            python_library(name='foo2', sources=[])
            python_distribution(
                name='foo3',
                dependencies=['src/python/foo/bar:bar2'],
                provides=setup_py(name='foo3', version='3.4.5'),
            )
            """
        ),
    )

    assert_is_owner(
        exporting_owner_rule_runner, "src/python/foo/bar:bar1", "src/python/foo/bar:bar1"
    )
    assert_is_owner(
        exporting_owner_rule_runner, "src/python/foo/bar:bar1", "src/python/foo/bar/baz:baz1"
    )

    assert_is_owner(exporting_owner_rule_runner, "src/python/foo:foo1", "src/python/foo:foo1")

    assert_is_owner(exporting_owner_rule_runner, "src/python/foo:foo3", "src/python/foo:foo3")
    assert_is_owner(exporting_owner_rule_runner, "src/python/foo:foo3", "src/python/foo/bar:bar2")
    assert_is_owner(
        exporting_owner_rule_runner, "src/python/foo:foo3", "src/python/foo/bar:bar-resources"
    )

    assert_no_owner(exporting_owner_rule_runner, "src/python/foo:foo2")
    assert_ambiguous_owner(exporting_owner_rule_runner, "src/python/foo/bar/baz:baz2")


def test_get_owner_siblings(exporting_owner_rule_runner: RuleRunner) -> None:
    exporting_owner_rule_runner.add_to_build_file(
        "src/python/siblings",
        textwrap.dedent(
            """
            python_library(name='sibling1', sources=[])
            python_distribution(
                name='sibling2',
                dependencies=['src/python/siblings:sibling1'],
                provides=setup_py(name='siblings', version='2.2.2'),
            )
            """
        ),
    )

    assert_is_owner(
        exporting_owner_rule_runner, "src/python/siblings:sibling2", "src/python/siblings:sibling1"
    )
    assert_is_owner(
        exporting_owner_rule_runner, "src/python/siblings:sibling2", "src/python/siblings:sibling2"
    )


def test_get_owner_not_an_ancestor(exporting_owner_rule_runner: RuleRunner) -> None:
    exporting_owner_rule_runner.add_to_build_file(
        "src/python/notanancestor/aaa",
        textwrap.dedent(
            """
            python_library(name='aaa', sources=[])
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

    assert_no_owner(exporting_owner_rule_runner, "src/python/notanancestor/aaa")
    assert_is_owner(
        exporting_owner_rule_runner, "src/python/notanancestor/bbb", "src/python/notanancestor/bbb"
    )


def test_get_owner_multiple_ancestor_generations(exporting_owner_rule_runner: RuleRunner) -> None:
    exporting_owner_rule_runner.add_to_build_file(
        "src/python/aaa/bbb/ccc",
        textwrap.dedent(
            """
            python_library(name='ccc', sources=[])
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

    assert_is_owner(exporting_owner_rule_runner, "src/python/aaa/bbb", "src/python/aaa/bbb/ccc")
    assert_is_owner(exporting_owner_rule_runner, "src/python/aaa/bbb", "src/python/aaa/bbb")
    assert_is_owner(exporting_owner_rule_runner, "src/python/aaa", "src/python/aaa")


def test_validate_args() -> None:
    with pytest.raises(InvalidSetupPyArgs):
        validate_args(("bdist_wheel", "upload"))
    with pytest.raises(InvalidSetupPyArgs):
        validate_args(("sdist", "-d", "new_distdir/"))
    with pytest.raises(InvalidSetupPyArgs):
        validate_args(("--dist-dir", "new_distdir/", "sdist"))

    validate_args(("sdist",))
    validate_args(("bdist_wheel", "--foo"))


def test_distutils_repr() -> None:
    testdata = {
        "foo": "bar",
        "baz": {"qux": [123, 456], "quux": ("abc", b"xyz"), "corge": {1, 2, 3}},
        "various_strings": ["x'y", "aaa\nbbb"],
    }
    expected = """
{
    'foo': 'bar',
    'baz': {
        'qux': [
            123,
            456,
        ],
        'quux': (
            'abc',
            'xyz',
        ),
        'corge': {
            1,
            2,
            3,
        },
    },
    'various_strings': [
        'x\\\'y',
        \"\"\"aaa\nbbb\"\"\",
    ],
}
""".strip()
    assert expected == distutils_repr(testdata)


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
