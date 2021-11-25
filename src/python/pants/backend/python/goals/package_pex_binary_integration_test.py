# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
import subprocess
from textwrap import dedent

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.goals import package_pex_binary
from pants.backend.python.goals.package_pex_binary import PexBinaryFieldSet
from pants.backend.python.target_types import PexBinary, PexLayout, PythonSourcesGeneratorTarget
from pants.backend.python.util_rules import pex_from_targets
from pants.build_graph.address import Address
from pants.core.goals.package import BuiltPackage
from pants.core.target_types import FilesGeneratorTarget, RelocatedFiles, ResourcesGeneratorTarget
from pants.core.target_types import rules as core_target_types_rules
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *package_pex_binary.rules(),
            *pex_from_targets.rules(),
            *target_types_rules.rules(),
            *core_target_types_rules(),
            QueryRule(BuiltPackage, [PexBinaryFieldSet]),
        ],
        target_types=[
            FilesGeneratorTarget,
            PexBinary,
            PythonSourcesGeneratorTarget,
            RelocatedFiles,
            ResourcesGeneratorTarget,
        ],
    )
    rule_runner.set_options([], env_inherit={"PATH", "PYENV_ROOT", "HOME"})
    return rule_runner


def test_warn_files_targets(rule_runner: RuleRunner, caplog) -> None:
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
            "src/py/project/app.py": "print('hello')",
            "src/py/project/BUILD": dedent(
                """\
                pex_binary(
                    dependencies=['assets:files', 'assets:relocated', 'assets:resources'],
                    entry_point="none",
                )
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("src/py/project"))
    field_set = PexBinaryFieldSet.create(tgt)

    assert not caplog.records
    result = rule_runner.request(BuiltPackage, [field_set])
    assert caplog.records
    assert f"The `pex_binary` target {tgt.address} transitively depends on" in caplog.text
    assert "assets/f.txt:files" in caplog.text
    assert "assets:relocated" in caplog.text
    assert "assets:resources" not in caplog.text

    assert len(result.artifacts) == 1
    assert result.artifacts[0].relpath == "src.py.project/project.pex"


@pytest.mark.parametrize(
    "layout",
    [pytest.param(layout, id=layout.value) for layout in PexLayout],
)
def test_layout(rule_runner: RuleRunner, layout: PexLayout) -> None:
    rule_runner.write_files(
        {
            "src/py/project/app.py": "print('hello')",
            "src/py/project/BUILD": dedent(
                f"""\
                python_sources(name="lib")
                pex_binary(
                    entry_point="app.py",
                    layout="{layout.value}",
                )
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("src/py/project"))
    field_set = PexBinaryFieldSet.create(tgt)
    result = rule_runner.request(BuiltPackage, [field_set])
    assert len(result.artifacts) == 1
    expected_pex_relpath = "src.py.project/project.pex"
    assert expected_pex_relpath == result.artifacts[0].relpath

    rule_runner.write_digest(result.digest)
    executable = os.path.join(
        rule_runner.build_root,
        expected_pex_relpath
        if PexLayout.ZIPAPP is layout
        else os.path.join(expected_pex_relpath, "__main__.py"),
    )
    assert b"hello\n" == subprocess.run([executable], check=True, stdout=subprocess.PIPE).stdout
