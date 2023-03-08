# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path, PurePath
from typing import Iterable, Mapping, Sequence, TypeVar

import pytest

from pants.core.util_rules import asdf
from pants.core.util_rules.asdf import AsdfToolPathsRequest, AsdfToolPathsResult, get_asdf_data_dir
from pants.core.util_rules.environments import (
    DockerEnvironmentTarget,
    DockerImageField,
    EnvironmentTarget,
    LocalEnvironmentTarget,
    RemoteEnvironmentTarget,
)
from pants.engine.addresses import Address
from pants.engine.env_vars import CompleteEnvironmentVars, EnvironmentVars
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner
from pants.util.contextutil import temporary_dir

_T = TypeVar("_T")


def materialize_indices(sequence: Sequence[_T], indices: Iterable[int]) -> tuple[_T, ...]:
    return tuple(sequence[i] for i in indices)


@contextmanager
def fake_asdf_root(
    fake_versions: list[str],
    fake_home_versions: list[int],
    fake_local_versions: list[int],
    *,
    tool_name: str,
):
    with temporary_dir() as home_dir, temporary_dir() as asdf_dir:
        fake_dirs: list[Path] = []
        fake_version_dirs: list[str] = []

        fake_home_dir = Path(home_dir)
        fake_tool_versions = fake_home_dir / ".tool-versions"
        fake_home_versions_str = " ".join(materialize_indices(fake_versions, fake_home_versions))
        fake_tool_versions.write_text(f"nodejs lts\njava 8\n{tool_name} {fake_home_versions_str}\n")

        fake_asdf_dir = Path(asdf_dir)
        fake_asdf_plugin_dir = fake_asdf_dir / "plugins" / tool_name
        fake_asdf_installs_dir = fake_asdf_dir / "installs" / tool_name

        fake_dirs.extend(
            [fake_home_dir, fake_asdf_dir, fake_asdf_plugin_dir, fake_asdf_installs_dir]
        )

        for version in fake_versions:
            fake_version_path = fake_asdf_installs_dir / version / "bin"
            fake_version_dirs.append(f"{fake_version_path}")
            fake_dirs.append(fake_version_path)

        for fake_dir in fake_dirs:
            fake_dir.mkdir(parents=True, exist_ok=True)

        yield (
            home_dir,
            asdf_dir,
            fake_version_dirs,
            # fake_home_version_dirs
            materialize_indices(fake_version_dirs, fake_home_versions),
            # fake_local_version_dirs
            materialize_indices(fake_version_dirs, fake_local_versions),
        )


def test_get_asdf_dir() -> None:
    home = PurePath("♡")
    default_root = home / ".asdf"
    explicit_root = home / "explicit"

    assert explicit_root == get_asdf_data_dir(
        EnvironmentVars({"ASDF_DATA_DIR": f"{explicit_root}"})
    )
    assert default_root == get_asdf_data_dir(EnvironmentVars({"HOME": f"{home}"}))
    assert get_asdf_data_dir(EnvironmentVars({})) is None


def get_asdf_paths(
    rule_runner: RuleRunner,
    env_tgt: EnvironmentTarget,
    env: Mapping[str, str],
    *,
    standard: bool,
    local: bool,
) -> AsdfToolPathsResult:
    rule_runner.set_session_values(
        {
            CompleteEnvironmentVars: CompleteEnvironmentVars(env),
        }
    )
    return rule_runner.request(
        AsdfToolPathsResult,
        [
            AsdfToolPathsRequest(
                env_tgt=env_tgt,
                tool_name="python",
                tool_description="<test>",
                resolve_standard=standard,
                resolve_local=local,
                paths_option_name="<test>",
            )
        ],
    )


@pytest.mark.parametrize(
    ("env_tgt_type", "should_have_values"),
    (
        (LocalEnvironmentTarget, True),
        (None, True),
        (DockerEnvironmentTarget, False),
        (RemoteEnvironmentTarget, False),
    ),
)
def test_get_asdf_paths(
    env_tgt_type: type[LocalEnvironmentTarget]
    | type[DockerEnvironmentTarget]
    | type[RemoteEnvironmentTarget]
    | None,
    should_have_values: bool,
) -> None:
    # 3.9.4 is intentionally "left out" so that it's only found if the "all installs" fallback is
    # used
    all_python_versions = ["2.7.14", "3.5.5", "3.7.10", "3.9.4", "3.9.5"]
    asdf_home_versions = [0, 1, 2]
    asdf_local_versions = [2, 1, 4]
    asdf_local_versions_str = " ".join(
        materialize_indices(all_python_versions, asdf_local_versions)
    )
    rule_runner = RuleRunner(
        rules=[
            *asdf.rules(),
            QueryRule(AsdfToolPathsResult, (AsdfToolPathsRequest,)),
        ]
    )
    rule_runner.write_files(
        {
            ".tool-versions": "\n".join(
                [
                    "nodejs 16.0.1",
                    "java current",
                    f"python {asdf_local_versions_str}",
                    "rust 1.52.0",
                ]
            )
        }
    )

    with fake_asdf_root(
        all_python_versions, asdf_home_versions, asdf_local_versions, tool_name="python"
    ) as (
        home_dir,
        asdf_dir,
        expected_asdf_paths,
        expected_asdf_home_paths,
        expected_asdf_local_paths,
    ):
        extra_kwargs: dict = {}
        if env_tgt_type is DockerEnvironmentTarget:
            extra_kwargs = {
                DockerImageField.alias: "my_img",
            }
        env_tgt = EnvironmentTarget(
            env_tgt_type(extra_kwargs, Address("flem")) if env_tgt_type is not None else None
        )

        # Check the "all installed" fallback
        result = get_asdf_paths(
            rule_runner, env_tgt, {"ASDF_DATA_DIR": asdf_dir}, standard=True, local=False
        )
        all_paths = result.standard_tool_paths

        result = get_asdf_paths(
            rule_runner,
            env_tgt,
            {"HOME": home_dir, "ASDF_DATA_DIR": asdf_dir},
            standard=True,
            local=True,
        )
        home_paths = result.standard_tool_paths
        local_paths = result.local_tool_paths

        if should_have_values:
            # The order the filesystem returns the "installed" folders is arbitrary
            assert set(expected_asdf_paths) == set(all_paths)

            # These have a fixed order defined by the `.tool-versions` file
            assert expected_asdf_home_paths == home_paths
            assert expected_asdf_local_paths == local_paths
        else:
            # asdf bails quickly on non-local environments
            assert () == all_paths
            assert () == home_paths
            assert () == local_paths
