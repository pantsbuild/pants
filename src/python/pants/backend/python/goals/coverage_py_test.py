# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent
from typing import List, Optional

import pytest

from pants.backend.python.goals.coverage_py import CoverageSubsystem, create_coverage_config
from pants.engine.fs import (
    EMPTY_DIGEST,
    CreateDigest,
    Digest,
    DigestContents,
    FileContent,
    PathGlobs,
)
from pants.testutil.option_util import create_subsystem
from pants.testutil.rule_runner import MockGet, run_rule_with_mocks


def run_create_coverage_config_rule(coverage_config: Optional[str]) -> str:
    coverage = create_subsystem(CoverageSubsystem, config="some_file" if coverage_config else None)
    resolved_config: List[str] = []

    def mock_handle_config(request: CreateDigest) -> Digest:
        assert len(request) == 1
        assert request[0].path == ".coveragerc"
        assert isinstance(request[0], FileContent)
        assert request[0].is_executable is False
        resolved_config.append(request[0].content.decode())
        return EMPTY_DIGEST

    def mock_read_config(_: PathGlobs) -> DigestContents:
        # This shouldn't be called if no config file provided.
        assert coverage_config is not None
        return DigestContents(
            [FileContent(path="/dev/null/prelude", content=coverage_config.encode())]
        )

    mock_gets = [
        MockGet(output_type=DigestContents, input_type=PathGlobs, mock=mock_read_config),
        MockGet(output_type=Digest, input_type=CreateDigest, mock=mock_handle_config),
    ]

    result = run_rule_with_mocks(create_coverage_config, rule_args=[coverage], mock_gets=mock_gets)
    assert result.digest.fingerprint == EMPTY_DIGEST.fingerprint
    assert len(resolved_config) == 1
    return resolved_config[0]


def test_default_no_config() -> None:
    resolved_config = run_create_coverage_config_rule(coverage_config=None)
    assert resolved_config == dedent(
        """\
            [run]
            relative_files = True
            omit = 
            \ttest_runner.pex/*

        """  # noqa: W291
    )


def test_simple_config() -> None:
    config = dedent(
        """
      [run]
      branch = False
      relative_files = True
      jerry = HELLO
      """
    )
    resolved_config = run_create_coverage_config_rule(coverage_config=config)
    assert resolved_config == dedent(
        """\
            [run]
            branch = False
            relative_files = True
            jerry = HELLO
            omit = 
            \ttest_runner.pex/*

            """  # noqa: W291
    )


def test_config_no_run_section() -> None:
    config = dedent(
        """
      [report]
      ignore_errors = True
      """
    )
    resolved_config = run_create_coverage_config_rule(coverage_config=config)
    assert resolved_config == dedent(
        """\
            [report]
            ignore_errors = True

            [run]
            relative_files = True
            omit = 
            \ttest_runner.pex/*

            """  # noqa: W291
    )


def test_append_omits() -> None:
    config = dedent(
        """
      [run]
      omit =
        jerry/seinfeld/*.py
        # I find tinsel distracting
        festivus/tinsel/*.py
      """
    )
    resolved_config = run_create_coverage_config_rule(coverage_config=config)
    assert resolved_config == dedent(
        """\
            [run]
            omit = 
            \tjerry/seinfeld/*.py
            \tfestivus/tinsel/*.py
            \ttest_runner.pex/*
            relative_files = True

            """  # noqa: W291
    )


def test_invalid_relative_files_setting() -> None:
    config = dedent(
        """
      [run]
      relative_files = False
      """
    )
    with pytest.raises(
        ValueError, match="relative_files under the 'run' section must be set to True"
    ):
        run_create_coverage_config_rule(coverage_config=config)
