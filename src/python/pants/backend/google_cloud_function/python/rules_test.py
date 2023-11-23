# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import subprocess
from io import BytesIO
from textwrap import dedent
from zipfile import ZipFile

import pytest

from pants.backend.google_cloud_function.python.rules import PythonGoogleCloudFunctionFieldSet
from pants.backend.google_cloud_function.python.rules import (
    rules as python_google_cloud_function_rules,
)
from pants.backend.google_cloud_function.python.target_types import PythonGoogleCloudFunction
from pants.backend.google_cloud_function.python.target_types import rules as target_rules
from pants.backend.python.goals import package_pex_binary
from pants.backend.python.goals.package_pex_binary import PexBinaryFieldSet
from pants.backend.python.target_types import (
    PexBinary,
    PythonRequirementTarget,
    PythonSourcesGeneratorTarget,
)
from pants.backend.python.target_types_rules import rules as python_target_types_rules
from pants.core.goals import package
from pants.core.goals.package import BuiltPackage
from pants.core.target_types import (
    FilesGeneratorTarget,
    FileTarget,
    RelocatedFiles,
    ResourcesGeneratorTarget,
)
from pants.core.target_types import rules as core_target_types_rules
from pants.engine.addresses import Address
from pants.engine.fs import DigestContents
from pants.engine.internals.scheduler import ExecutionError
from pants.testutil.python_rule_runner import PythonRuleRunner
from pants.testutil.rule_runner import QueryRule


@pytest.fixture
def rule_runner() -> PythonRuleRunner:
    rule_runner = PythonRuleRunner(
        rules=[
            *package_pex_binary.rules(),
            *python_google_cloud_function_rules(),
            *target_rules(),
            *python_target_types_rules(),
            *core_target_types_rules(),
            *package.rules(),
            QueryRule(BuiltPackage, (PythonGoogleCloudFunctionFieldSet,)),
        ],
        target_types=[
            FileTarget,
            FilesGeneratorTarget,
            PexBinary,
            PythonGoogleCloudFunction,
            PythonRequirementTarget,
            PythonSourcesGeneratorTarget,
            RelocatedFiles,
            ResourcesGeneratorTarget,
        ],
    )
    rule_runner.set_options([], env_inherit={"PATH", "PYENV_ROOT", "HOME"})
    return rule_runner


def create_python_google_cloud_function(
    rule_runner: PythonRuleRunner,
    addr: Address,
    *,
    expected_extra_log_lines: tuple[str, ...],
    extra_args: list[str] | None = None,
) -> tuple[str, bytes]:
    rule_runner.set_options(
        [
            "--source-root-patterns=src/python",
            *(extra_args or ()),
        ],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    target = rule_runner.get_target(addr)
    built_asset = rule_runner.request(
        BuiltPackage, [PythonGoogleCloudFunctionFieldSet.create(target)]
    )
    assert expected_extra_log_lines == built_asset.artifacts[0].extra_log_lines
    digest_contents = rule_runner.request(DigestContents, [built_asset.digest])
    assert len(digest_contents) == 1
    relpath = built_asset.artifacts[0].relpath
    assert relpath is not None
    return relpath, digest_contents[0].content


@pytest.fixture
def complete_platform(rule_runner: PythonRuleRunner) -> bytes:
    rule_runner.write_files(
        {
            "pex_exe/BUILD": dedent(
                """\
                python_requirement(name="req", requirements=["pex==2.1.99"])
                pex_binary(dependencies=[":req"], script="pex")
                """
            ),
        }
    )
    result = rule_runner.request(
        BuiltPackage, [PexBinaryFieldSet.create(rule_runner.get_target(Address("pex_exe")))]
    )
    rule_runner.write_digest(result.digest)
    pex_executable = os.path.join(rule_runner.build_root, "pex_exe/pex_exe.pex")
    return subprocess.run(
        args=[pex_executable, "interpreter", "inspect", "-mt"],
        env=dict(PEX_MODULE="pex.cli", **os.environ),
        check=True,
        stdout=subprocess.PIPE,
    ).stdout


def test_warn_files_targets(rule_runner: PythonRuleRunner, caplog) -> None:
    rule_runner.write_files(
        {
            "assets/f.txt": "",
            "assets/BUILD": dedent(
                """\
                files(name='files', sources=['f.txt'])
                relocated_files(
                    name='relocated',
                    files_targets=[':files'],
                    src='assets',
                    dest='new_assets',
                )

                # Resources are fine.
                resources(name='resources', sources=['f.txt'])
                """
            ),
            "src/py/project/__init__.py": "",
            "src/py/project/app.py": dedent(
                """\
                def handler(event, context):
                    print('Hello, World!')
                """
            ),
            "src/py/project/BUILD": dedent(
                """\
                python_sources(
                    name='lib',
                    dependencies=['assets:files', 'assets:relocated', 'assets:resources'],
                )

                python_google_cloud_function(
                    name='lambda',
                    dependencies=[':lib'],
                    handler='foo.bar.hello_world:handler',
                    runtime='python37',
                    type='event',
                )
                """
            ),
        }
    )

    assert not caplog.records
    zip_file_relpath, _ = create_python_google_cloud_function(
        rule_runner,
        Address("src/py/project", target_name="lambda"),
        expected_extra_log_lines=(
            "    Runtime: python37",
            "    Handler: handler",
        ),
    )
    assert caplog.records
    assert "src.py.project/lambda.zip" == zip_file_relpath
    assert (
        "The target src/py/project:lambda (`python_google_cloud_function`) transitively depends on"
        in caplog.text
    )
    assert "assets/f.txt:files" in caplog.text
    assert "assets:relocated" in caplog.text
    assert "assets:resources" not in caplog.text


@pytest.mark.parametrize(
    ("ics", "runtime"),
    [
        pytest.param(["==3.7.*"], None, id="runtime inferred from ICs"),
        pytest.param(None, "python37", id="runtime explicitly set"),
    ],
)
def test_create_hello_world_gcf(
    ics: list[str] | None, runtime: None | str, rule_runner: PythonRuleRunner
) -> None:
    rule_runner.write_files(
        {
            "src/python/foo/bar/hello_world.py": dedent(
                """
                import mureq

                def handler(event, context):
                    print('Hello, World!')
                """
            ),
            "src/python/foo/bar/BUILD": dedent(
                f"""
                python_requirement(name="mureq", requirements=["mureq==0.2"])
                python_sources(interpreter_constraints={ics!r})

                python_google_cloud_function(
                    name='gcf',
                    handler='foo.bar.hello_world:handler',
                    runtime={runtime!r},
                    type='event',
                )
                """
            ),
        }
    )

    zip_file_relpath, content = create_python_google_cloud_function(
        rule_runner,
        Address("src/python/foo/bar", target_name="gcf"),
        expected_extra_log_lines=(
            "    Runtime: python37",
            "    Handler: handler",
        ),
    )
    assert "src.python.foo.bar/gcf.zip" == zip_file_relpath

    zipfile = ZipFile(BytesIO(content))
    names = set(zipfile.namelist())
    assert "mureq/__init__.py" in names
    assert "foo/bar/hello_world.py" in names
    assert zipfile.read("main.py") == b"from foo.bar.hello_world import handler as handler"


def test_collisions_ok(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/python/foo/bar/hello_world.py": dedent(
                """
                def handler(event, context):
                    print('Hello, World!')
                """
            ),
            "src/python/foo/bar/BUILD": dedent(
                """
                # Per https://github.com/pantsbuild/pants/issues/20224, these both package their `tests/`
                # folder at the top level with non-equal __init__.py and test_defaults.py within it.
                python_requirement(name="django-hosts", requirements=["django-hosts==5.1"])
                python_requirement(name="draftjs-exporter", requirements=["draftjs-exporter==2.1.7"])
                python_sources()

                python_google_cloud_function(
                    name='gcf-ok',
                    handler='foo.bar.hello_world:handler',
                    dependencies=[":django-hosts", ":draftjs-exporter"],
                    runtime='python39',
                    collisions_ok=True,
                    type='event',
                )

                python_google_cloud_function(
                    name='gcf-error',
                    handler='foo.bar.hello_world:handler',
                    dependencies=[":django-hosts", ":draftjs-exporter"],
                    runtime='python39',
                    type='event',
                )
                """
            ),
        }
    )

    # Verify - without the flag, we get an error
    target = rule_runner.get_target(Address("src/python/foo/bar", target_name="gcf-error"))
    with pytest.raises(ExecutionError, match="Encountered collisions"):
        rule_runner.request(BuiltPackage, [PythonGoogleCloudFunctionFieldSet.create(target)])

    # Exercise/Verify - passing collisions_ok resolves the issue
    create_python_google_cloud_function(
        rule_runner,
        Address("src/python/foo/bar", target_name="gcf-ok"),
        expected_extra_log_lines=(
            "    Runtime: python39",
            "    Handler: handler",
        ),
    )
