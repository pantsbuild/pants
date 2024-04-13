# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

from pants.backend.python.goals.coverage_py import (
    CoverageSubsystem,
    create_or_update_coverage_config,
    get_branch_value_from_config,
    get_namespace_value_from_config,
)
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.engine.fs import (
    EMPTY_DIGEST,
    EMPTY_SNAPSHOT,
    CreateDigest,
    Digest,
    DigestContents,
    FileContent,
)
from pants.testutil.option_util import create_subsystem
from pants.testutil.rule_runner import MockGet, RuleRunner, run_rule_with_mocks


def resolve_config(path: str | None, content: str | None) -> str:
    coverage_subsystem = create_subsystem(CoverageSubsystem, config=path, config_discovery=True)
    resolved_config: list[str] = []

    def mock_find_existing_config(request: ConfigFilesRequest) -> ConfigFiles:
        if request.specified:
            assert path is not None
            snapshot = RuleRunner().make_snapshot_of_empty_files([path])
        else:
            snapshot = EMPTY_SNAPSHOT
        return ConfigFiles(snapshot)

    def mock_read_existing_config(_: Digest) -> DigestContents:
        # This shouldn't be called if no config file provided.
        assert path is not None
        assert content is not None
        return DigestContents([FileContent(path, content.encode())])

    def mock_create_final_config(request: CreateDigest) -> Digest:
        assert len(request) == 1
        assert isinstance(request[0], FileContent)
        assert request[0].path == path if path is not None else ".coveragerc"
        assert request[0].is_executable is False
        resolved_config.append(request[0].content.decode())
        return EMPTY_DIGEST

    mock_gets = [
        MockGet(
            output_type=ConfigFiles,
            input_types=(ConfigFilesRequest,),
            mock=mock_find_existing_config,
        ),
        MockGet(output_type=DigestContents, input_types=(Digest,), mock=mock_read_existing_config),
        MockGet(output_type=Digest, input_types=(CreateDigest,), mock=mock_create_final_config),
    ]

    result = run_rule_with_mocks(
        create_or_update_coverage_config,
        rule_args=[coverage_subsystem],
        mock_gets=mock_gets,  # type: ignore[arg-type]
    )
    assert result.digest == EMPTY_DIGEST
    assert len(resolved_config) == 1
    return resolved_config[0]


def test_no_config() -> None:
    assert resolve_config(None, None) == dedent(
        """\
        [run]
        relative_files = True
        omit = 
        \tpytest.pex/*

        """  # noqa: W291
    )


def test_no_run_section() -> None:
    assert (
        resolve_config(
            "pyproject.toml",
            dedent(
                """\
                [tool.coverage.report]
                ignore_errors = true

                [tool.isort]
                foo = "bar"
                """
            ),
        )
        == dedent(
            """\
            [tool.isort]
            foo = "bar"

            [tool.coverage.report]
            ignore_errors = true

            [tool.coverage.run]
            relative_files = true
            omit = [ "pytest.pex/*",]
            """
        )
    )
    assert (
        resolve_config(
            ".coveragerc",
            dedent(
                """\
                [report]
                ignore_errors: True
                """
            ),
        )
        == dedent(
            """\
            [report]
            ignore_errors = True

            [run]
            relative_files = True
            omit = 
            \tpytest.pex/*

            """  # noqa: W291
        )
    )
    assert (
        resolve_config(
            "setup.cfg",
            dedent(
                """\
                [coverage:report]
                ignore_errors: True
                """
            ),
        )
        == dedent(
            """\
            [coverage:report]
            ignore_errors = True

            [coverage:run]
            relative_files = True
            omit = 
            \tpytest.pex/*

            """  # noqa: W291
        )
    )


def test_update_run_section() -> None:
    assert (
        resolve_config(
            "pyproject.toml",
            dedent(
                """\
                [tool.coverage.run]
                relative_files = false
                omit = ["e1"]
                foo = "bar"
                """
            ),
        )
        == dedent(
            """\
            [tool.coverage.run]
            relative_files = true
            omit = [ "e1", "pytest.pex/*",]
            foo = "bar"
            """
        )
    )
    assert (
        resolve_config(
            ".coveragerc",
            dedent(
                """\
                [run]
                relative_files: False
                omit:
                  e1
                foo: bar
                """
            ),
        )
        == dedent(
            """\
            [run]
            relative_files = True
            omit = 
            \te1
            \tpytest.pex/*
            foo = bar

            """  # noqa: W291
        )
    )
    assert (
        resolve_config(
            "setup.cfg",
            dedent(
                """\
                [coverage:run]
                relative_files: False
                omit:
                  e1
                foo: bar
                """
            ),
        )
        == dedent(
            """\
            [coverage:run]
            relative_files = True
            omit = 
            \te1
            \tpytest.pex/*
            foo = bar

            """  # noqa: W291
        )
    )


def branch(path: str, content: str) -> bool:
    fc = FileContent(path, content.encode())
    return get_branch_value_from_config(fc)


def test_get_branch_value_from_config() -> None:
    assert (
        branch(
            "pyproject.toml",
            dedent(
                """\
        [tool.coverage.run]
        relative_files = false
        foo = "bar"
        """
            ),
        )
        is False
    )

    assert (
        branch(
            "pyproject.toml",
            dedent(
                """\
        [tool.coverage.run]
        relative_files = false
        branch = true
        foo = "bar"
        """
            ),
        )
        is True
    )

    assert (
        branch(
            "pyproject.toml",
            dedent(
                """\
            [tool.coverage]
                [tool.coverage.run]
                branch = true
            """
            ),
        )
        is True
    )

    assert (
        branch(
            ".coveragerc",
            dedent(
                """\
                [run]
                relative_files: False
                branch: False
                foo: bar
                """
            ),
        )
        is False
    )

    assert (
        branch(
            ".coveragerc",
            dedent(
                """\
                    [run]
                    relative_files: False
                    branch: True
                    foo: bar
                    """
            ),
        )
        is True
    )

    assert (
        branch(
            "setup.cfg",
            dedent(
                """\
                [coverage:run]
                relative_files: False
                branch: False
                foo: bar
                """
            ),
        )
        is False
    )

    assert (
        branch(
            "setup.cfg",
            dedent(
                """\
                    [coverage:run]
                    relative_files: False
                    branch: True
                    foo: bar
                    """
            ),
        )
        is True
    )


def namespace(path: str, content: str) -> bool:
    fc = FileContent(path, content.encode())
    return get_namespace_value_from_config(fc)


def test_get_namespace_value_from_config() -> None:
    assert (
        namespace(
            "pyproject.toml",
            dedent(
                """\
        [tool.coverage.report]
        foo = "bar"
        """
            ),
        )
        is False
    )

    assert (
        namespace(
            "pyproject.toml",
            dedent(
                """\
        [tool.coverage.report]
        include_namespace_packages = true
        """
            ),
        )
        is True
    )

    assert (
        namespace(
            "pyproject.toml",
            dedent(
                """\
            [tool.coverage]
                [tool.coverage.report]
                include_namespace_packages = true
            """
            ),
        )
        is True
    )

    assert (
        namespace(
            ".coveragerc",
            dedent(
                """\
                [report]
                foo: bar
                """
            ),
        )
        is False
    )

    assert (
        namespace(
            ".coveragerc",
            dedent(
                """\
                    [report]
                    include_namespace_packages: True
                    """
            ),
        )
        is True
    )

    assert (
        namespace(
            "setup.cfg",
            dedent(
                """\
                [coverage:report]
                foo: bar
                """
            ),
        )
        is False
    )

    assert (
        namespace(
            "setup.cfg",
            dedent(
                """\
                    [coverage:report]
                    include_namespace_packages: True
                    """
            ),
        )
        is True
    )
