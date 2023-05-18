# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent

import pytest

from pants.core.goals import package
from pants.core.goals.package import BuiltPackage, BuiltPackageArtifact, Package, PackageFieldSet
from pants.engine.fs import CreateDigest, Digest, FileContent
from pants.engine.internals.selectors import Get
from pants.engine.rules import rule
from pants.engine.target import StringField, Target
from pants.engine.unions import UnionRule
from pants.testutil.rule_runner import RuleRunner


class MockTypeField(StringField):
    alias = "type"

    def synth(self, base_path: Path) -> tuple[CreateDigest, tuple[Path, ...]]:
        if self.value == "single_file":
            return (CreateDigest([FileContent(str(base_path), b"single")]), (base_path,))

        elif self.value == "multiple_files":
            a = base_path / "a"
            b = base_path / "b"
            return (
                CreateDigest(
                    [FileContent(str(a), b"multiple: a"), FileContent(str(b), b"multiple: b")]
                ),
                (a, b),
            )

        elif self.value == "directory":
            a = base_path / "a"
            b = base_path / "b"
            return (
                CreateDigest(
                    [
                        FileContent(str(a), b"directory: a"),
                        FileContent(str(b), b"directory: b"),
                    ]
                ),
                (base_path,),
            )

        raise ValueError(f"don't understand {self.value}")


class MockTarget(Target):
    alias = "mock"
    core_fields = (MockTypeField,)


@dataclass(frozen=True)
class MockPackageFieldSet(PackageFieldSet):
    required_fields = (MockTypeField,)

    type: MockTypeField


@rule
async def package_mock_target(field_set: MockPackageFieldSet) -> BuiltPackage:
    base_path = Path(f"base/{field_set.address.target_name}")
    create_digest, relpaths = field_set.type.synth(base_path)
    digest = await Get(Digest, CreateDigest, create_digest)
    return BuiltPackage(
        digest, tuple(BuiltPackageArtifact(relpath=str(relpath)) for relpath in relpaths)
    )


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *package.rules(),
            package_mock_target,
            UnionRule(PackageFieldSet, MockPackageFieldSet),
        ],
        target_types=[MockTarget],
    )


@pytest.fixture
def dist_base(rule_runner) -> Path:
    return Path(rule_runner.build_root, "dist/base")


def test_package_single_file_artifact(rule_runner: RuleRunner, dist_base: Path) -> None:
    rule_runner.write_files({"src/BUILD": "mock(name='x', type='single_file')"})
    result = rule_runner.run_goal_rule(
        Package,
        args=("src:x",),
        env_inherit={"HOME", "PATH", "PYENV_ROOT"},
    )

    assert result.exit_code == 0
    assert (dist_base / "x").read_text() == "single"


def test_package_directory_artifact(rule_runner: RuleRunner, dist_base: Path) -> None:
    rule_runner.write_files({"src/BUILD": "mock(name='x', type='directory')"})
    result = rule_runner.run_goal_rule(
        Package,
        args=("src:x",),
        env_inherit={"HOME", "PATH", "PYENV_ROOT"},
    )

    assert result.exit_code == 0
    assert (dist_base / "x/a").read_text() == "directory: a"
    assert (dist_base / "x/b").read_text() == "directory: b"


def test_package_multiple_artifacts(rule_runner: RuleRunner, dist_base: Path) -> None:
    rule_runner.write_files({"src/BUILD": "mock(name='x', type='multiple_files')"})
    result = rule_runner.run_goal_rule(
        Package,
        args=("src:x",),
        env_inherit={"HOME", "PATH", "PYENV_ROOT"},
    )

    assert result.exit_code == 0
    assert (dist_base / "x/a").read_text() == "multiple: a"
    assert (dist_base / "x/b").read_text() == "multiple: b"


def test_package_multiple_targets(rule_runner: RuleRunner, dist_base: Path) -> None:
    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                """\
                mock(name='x', type='single_file')
                mock(name='y', type='single_file')
                """
            )
        }
    )
    result = rule_runner.run_goal_rule(
        Package,
        args=("src:x", "src:y"),
        env_inherit={"HOME", "PATH", "PYENV_ROOT"},
    )

    assert result.exit_code == 0
    assert (dist_base / "x").read_text() == "single"
    assert (dist_base / "y").read_text() == "single"


@pytest.mark.parametrize("existing", ["file", "directory"])
@pytest.mark.parametrize("type", ["single_file", "directory"])
def test_package_replace_existing(
    existing: str, type: str, rule_runner: RuleRunner, dist_base: Path
) -> None:
    """All combinations of having existing contents (either file or directory) in dist/ and
    replacing it with file or directory package contents: the final result should be exactly the
    same as clearing dist/ and running package from scratch:

    - works
    - no extraneous files remaining within an artifact
    """
    existing_contents = (
        {"dist/base/x": "existing"}
        if existing == "file"
        else {"dist/base/x/a": "existing: a", "dist/base/x/c": "existing: c"}
    )
    rule_runner.write_files({**existing_contents, "src/BUILD": f"mock(name='x', type='{type}')"})
    result = rule_runner.run_goal_rule(
        Package,
        args=("src:x",),
        env_inherit={"HOME", "PATH", "PYENV_ROOT"},
    )

    assert result.exit_code == 0

    if type == "single_file":
        assert (dist_base / "x").read_text() == "single"
    else:
        a = dist_base / "x/a"
        b = dist_base / "x/b"
        assert set((dist_base / "x").iterdir()) == {a, b}
        assert a.read_text() == "directory: a"
        assert b.read_text() == "directory: b"
