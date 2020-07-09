# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent
from typing import List, Optional

import pytest

from pants.backend.python.rules.coverage import CoverageSubsystem, create_coverage_config
from pants.engine.fs import CreateDigest, Digest, DigestContents, FileContent, PathGlobs, Snapshot
from pants.testutil.engine.util import MockGet, create_subsystem, run_rule
from pants.testutil.test_base import TestBase


class TestCoverageConfig(TestBase):
    def run_create_coverage_config_rule(self, coverage_config: Optional[str]) -> str:
        coverage = create_subsystem(
            CoverageSubsystem, config="some_file" if coverage_config else None
        )
        resolved_config: List[str] = []

        def fake_handle_config(fcs):
            assert len(fcs) == 1
            assert fcs[0].path == ".coveragerc"
            assert fcs[0].is_executable is False
            resolved_config.append(fcs[0].content.decode())
            return Digest("jerry", 30)

        def fake_read_config(digest):
            # fake_read_config shouldn't get called if no config file provided
            assert coverage_config is not None
            return DigestContents(
                [FileContent(path="/dev/null/prelude", content=coverage_config.encode())]
            )

        mock_gets = [
            MockGet(
                product_type=Snapshot,
                subject_type=PathGlobs,
                mock=lambda _: Snapshot(Digest("bosco", 30), ("/dev/null/someconfig",), ()),
            ),
            MockGet(product_type=DigestContents, subject_type=Digest, mock=fake_read_config,),
            MockGet(product_type=Digest, subject_type=CreateDigest, mock=fake_handle_config),
        ]

        result = run_rule(create_coverage_config, rule_args=[coverage], mock_gets=mock_gets)
        assert result.digest.fingerprint == "jerry"
        assert len(resolved_config) == 1
        return resolved_config[0]

    def test_default_no_config(self) -> None:
        resolved_config = self.run_create_coverage_config_rule(coverage_config=None)
        assert resolved_config == dedent(
            """\
                [run]
                branch = True
                relative_files = True
                omit = 
                \ttest_runner.pex/*

            """  # noqa: W291
        )

    def test_simple_config(self) -> None:
        config = dedent(
            """
          [run]
          branch = False
          relative_files = True
          jerry = HELLO
          """
        )
        resolved_config = self.run_create_coverage_config_rule(coverage_config=config)
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

    def test_config_no_run_section(self) -> None:
        config = dedent(
            """
          [report]
          ignore_errors = True
          """
        )
        resolved_config = self.run_create_coverage_config_rule(coverage_config=config)
        assert resolved_config == dedent(
            """\
                [report]
                ignore_errors = True

                [run]
                branch = True
                relative_files = True
                omit = 
                \ttest_runner.pex/*

                """  # noqa: W291
        )

    def test_append_omits(self) -> None:
        config = dedent(
            """
          [run]
          omit =
            jerry/seinfeld/*.py
            # I find tinsel distracting
            festivus/tinsel/*.py
          """
        )
        resolved_config = self.run_create_coverage_config_rule(coverage_config=config)
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

    def test_invalid_relative_files_setting(self) -> None:
        config = dedent(
            """
          [run]
          relative_files = False
          """
        )
        with pytest.raises(
            ValueError, match="relative_files under the 'run' section must be set to True"
        ):
            self.run_create_coverage_config_rule(coverage_config=config)
