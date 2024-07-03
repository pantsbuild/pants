# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pathlib import PurePath

import pytest

from pants.backend.tools.semgrep import rules
from pants.backend.tools.semgrep.rules import AllSemgrepConfigs
from pants.engine.addresses import Address
from pants.engine.fs import Paths


def configs(strs: dict[str, set[str]]) -> AllSemgrepConfigs:
    return AllSemgrepConfigs(
        {PurePath(d): {PurePath(f) for f in files} for d, files in strs.items()}
    )


@pytest.mark.parametrize(
    ("paths", "expected"),
    [
        pytest.param((), configs({}), id="nothing"),
        pytest.param(
            ("foo/bar/.semgrep.yml",),
            configs({"foo/bar": {"foo/bar/.semgrep.yml"}}),
            id="semgrep_file",
        ),
        pytest.param(
            ("foo/bar/.semgrep/baz.yml", "foo/bar/.semgrep/qux.yml"),
            configs({"foo/bar": {"foo/bar/.semgrep/baz.yml", "foo/bar/.semgrep/qux.yml"}}),
            id="semgrep_dir",
        ),
        pytest.param(
            (
                "foo/bar/.semgrep.yml",
                "foo/bar/.semgrep/baz.yml",
            ),
            configs({"foo/bar": {"foo/bar/.semgrep.yml", "foo/bar/.semgrep/baz.yml"}}),
            id="both_file_and_dir",
        ),
        pytest.param(
            (
                "foo/bar/.semgrep/.semgrep.yml",
                "foo/bar/.semgrep/baz1.yml",
                "foo/bar/.semgrep/quz/baz2.yml",
            ),
            configs({"foo/bar": {"foo/bar/.semgrep/.semgrep.yml", "foo/bar/.semgrep/baz1.yml", "foo/bar/.semgrep/quz/baz2.yml"}}),
            id="recursively_find_yamls",
        ),
        pytest.param(
            (
                "foo/.semgrep/baz.yml",
                "foo/bar/.semgrep.yml",
                "foo/bar/qux/.semgrep.yml",
            ),
            configs(
                {
                    "foo": {"foo/.semgrep/baz.yml"},
                    "foo/bar": {"foo/bar/.semgrep.yml"},
                    "foo/bar/qux": {"foo/bar/qux/.semgrep.yml"},
                }
            ),
            id="everything",
        ),
        # at the top level should be okay too
        pytest.param(
            (".semgrep.yml", ".semgrep/foo.yml"),
            configs({"": {".semgrep.yml", ".semgrep/foo.yml"}}),
            id="top_level",
        ),
    ],
)
def test_group_by_group_by_semgrep_dir(paths: tuple[str, ...], expected: AllSemgrepConfigs):
    input = Paths(files=paths, dirs=())
    result = rules._group_by_semgrep_dir(".semgrep", input)
    assert result == expected


@pytest.mark.parametrize(
    ("config", "address", "expected"),
    [
        pytest.param(configs({}), Address(""), set(), id="nothing_root"),
        pytest.param(configs({}), Address("foo/bar"), set(), id="nothing_nested"),
        pytest.param(
            configs({"": {".semgrep.yml"}}),
            Address(""),
            {".semgrep.yml"},
            id="config_root_address_root",
        ),
        pytest.param(
            configs({"": {".semgrep.yml"}}),
            Address("foo/bar"),
            {".semgrep.yml"},
            id="config_root_address_nested",
        ),
        pytest.param(
            configs({"": {".semgrep.yml", ".semgrep/foo.yml"}}),
            Address(""),
            {".semgrep.yml", ".semgrep/foo.yml"},
            id="config_root_multiple_address_root",
        ),
        pytest.param(
            configs({"foo/bar": {"foo/bar/.semgrep.yml"}}),
            Address(""),
            set(),
            id="config_nested_address_root",
        ),
        pytest.param(
            configs({"foo/bar": {"foo/bar/.semgrep.yml"}}),
            Address("foo/bar"),
            {"foo/bar/.semgrep.yml"},
            id="config_nested_address_nested_matching",
        ),
        pytest.param(
            configs({"foo/bar": {"foo/bar/.semgrep.yml"}}),
            Address("foo/baz"),
            {},
            id="config_nested_address_nested_different",
        ),
        pytest.param(
            configs({"": {".semgrep.yml"}, "foo/bar": {"foo/bar/.semgrep.yml"}}),
            Address(""),
            {".semgrep.yml"},
            id="config_root_and_nested_address_root",
        ),
        pytest.param(
            configs({"": {".semgrep.yml"}, "foo/bar": {"foo/bar/.semgrep.yml"}}),
            Address("foo/bar"),
            {".semgrep.yml", "foo/bar/.semgrep.yml"},
            id="config_root_and_nested_address_nested",
        ),
    ],
)
def test_all_semgrep_configs_ancestor_configs(
    config: AllSemgrepConfigs, address: Address, expected: set[str]
):
    result = config.ancestor_configs(address)

    assert set(result) == {PurePath(p) for p in expected}
