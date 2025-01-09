# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.core.util_rules import config_files
from pants.core.util_rules.config_files import (
    ConfigFiles,
    ConfigFilesRequest,
    GatherConfigFilesByDirectoriesRequest,
    GatheredConfigFilesByDirectories,
)
from pants.engine.fs import PathGlobs, Snapshot
from pants.engine.internals.scheduler import ExecutionError
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *config_files.rules(),
            QueryRule(ConfigFiles, [ConfigFilesRequest]),
            QueryRule(GatheredConfigFilesByDirectories, [GatherConfigFilesByDirectoriesRequest]),
        ]
    )


def test_resolve_if_specified(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"c1": "", "c2": ""})

    def resolve(specified: list[str]) -> tuple[str, ...]:
        return rule_runner.request(
            ConfigFiles,
            [ConfigFilesRequest(specified=specified, specified_option_name="[subsystem].config")],
        ).snapshot.files

    assert resolve(["c1", "c2"]) == ("c1", "c2")
    assert resolve(["c1"]) == ("c1",)
    with pytest.raises(ExecutionError) as exc:
        resolve(["fake"])
    assert "fake" in str(exc.value)


def test_discover_config(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"c1": "", "c2": "", "c3": "foo", "c4": "bar"})

    def discover(
        existence: list[str], content: dict[str, bytes], *, specified: str | None = None
    ) -> tuple[str, ...]:
        return rule_runner.request(
            ConfigFiles,
            [
                ConfigFilesRequest(
                    specified=specified,
                    specified_option_name="foo",
                    discovery=True,
                    check_existence=existence,
                    check_content=content,
                )
            ],
        ).snapshot.files

    assert discover(["c1", "fake"], {"c3": b"foo", "c4": b"bad"}) == ("c1", "c3")
    assert discover(["c1"], {}) == ("c1",)
    assert discover([], {}) == ()
    assert discover(["fake"], {"c4": b"bad"}) == ()
    # Explicitly specifying turns off auto-discovery.
    assert discover(["c1"], {}, specified="c2") == ("c2",)


TEST_CONFIG_FILENAME = "myconfig.cfg"


def test_gather_config_files(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            TEST_CONFIG_FILENAME: "",
            f"foo/bar/{TEST_CONFIG_FILENAME}": "",
            f"hello/{TEST_CONFIG_FILENAME}": "",
            "hello/Foo.x": "",
            "hello/world/Foo.x": "",
            "foo/bar/Foo.x": "",
            "foo/bar/xyyzzy/Foo.x": "",
            "foo/blah/Foo.x": "",
        }
    )

    snapshot = rule_runner.request(Snapshot, [PathGlobs(["**/*.x"])])
    request = rule_runner.request(
        GatheredConfigFilesByDirectories,
        [
            GatherConfigFilesByDirectoriesRequest(
                tool_name="test", config_filename=TEST_CONFIG_FILENAME, filepaths=snapshot.files
            )
        ],
    )
    assert sorted(request.source_dir_to_config_file.items()) == [
        ("foo/bar", f"foo/bar/{TEST_CONFIG_FILENAME}"),
        ("foo/bar/xyyzzy", f"foo/bar/{TEST_CONFIG_FILENAME}"),
        ("foo/blah", TEST_CONFIG_FILENAME),
        ("hello", f"hello/{TEST_CONFIG_FILENAME}"),
        ("hello/world", f"hello/{TEST_CONFIG_FILENAME}"),
    ]
