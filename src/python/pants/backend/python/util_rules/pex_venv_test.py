# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import fnmatch
import io
import zipfile
from pathlib import Path

import pytest

from pants.backend.python.util_rules import pex_test_utils
from pants.backend.python.util_rules.pex import CompletePlatforms, Pex, PexPlatforms
from pants.backend.python.util_rules.pex import rules as pex_rules
from pants.backend.python.util_rules.pex_requirements import PexRequirements
from pants.backend.python.util_rules.pex_test_utils import create_pex_and_get_all_data
from pants.backend.python.util_rules.pex_venv import PexVenv, PexVenvLayout, PexVenvRequest
from pants.backend.python.util_rules.pex_venv import rules as pex_venv_rules
from pants.engine.fs import CreateDigest, DigestContents, FileContent
from pants.engine.internals.native_engine import Digest, Snapshot
from pants.engine.internals.scheduler import ExecutionError
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *pex_test_utils.rules(),
            *pex_rules(),
            *pex_venv_rules(),
            QueryRule(PexVenv, (PexVenvRequest,)),
            QueryRule(Snapshot, (CreateDigest,)),
        ],
    )


requirements = PexRequirements(["psycopg2-binary==2.9.6"])


@pytest.fixture
def sources(rule_runner: RuleRunner) -> Digest:
    return rule_runner.request(
        Digest, [CreateDigest([FileContent(path="first/party.py", content=b"")])]
    )


@pytest.fixture
def local_pex(rule_runner: RuleRunner, sources: Digest) -> Pex:
    result = create_pex_and_get_all_data(
        rule_runner,
        requirements=requirements,
        sources=sources,
        internal_only=False,
    )
    assert isinstance(result.pex, Pex)
    return result.pex


# at least one of these will be foreign
WIN_311 = "win-amd64-cp-311-cp311"
MAC_310 = "macosx_11_0-arm64-cp-310-cp310"

# subset of the complete platforms for MAC_310
MAC_310_CP = b"""{"path": "....", "compatible_tags": ["cp310-cp310-macosx_12_0_arm64", "cp310-cp310-macosx_12_0_universal2", "cp310-cp310-macosx_11_0_arm64", "py31-none-any", "py30-none-any"], "marker_environment": {"implementation_name": "cpython", "implementation_version": "3.10.10", "os_name": "posix", "platform_machine": "arm64", "platform_python_implementation": "CPython", "platform_release": "21.6.0", "platform_system": "Darwin", "platform_version": "Darwin Kernel Version 21.6.0: Wed Aug 10 14:28:35 PDT 2022; root:xnu-8020.141.5~2/RELEASE_ARM64_T8101", "python_full_version": "3.10.10", "python_version": "3.10", "sys_platform": "darwin"}}"""


@pytest.fixture
def foreign_pex(rule_runner: RuleRunner, sources: Digest) -> Pex:
    result = create_pex_and_get_all_data(
        rule_runner,
        requirements=requirements,
        sources=sources,
        platforms=PexPlatforms([WIN_311, MAC_310]),
        internal_only=False,
    )
    assert isinstance(result.pex, Pex)
    return result.pex


def run_and_validate(
    rule_runner: RuleRunner, request: PexVenvRequest, check_globs_exist: tuple[str, ...]
) -> PexVenv:
    venv = rule_runner.request(PexVenv, [request])

    assert venv.path == request.output_path

    snapshot = rule_runner.request(Snapshot, [venv.digest])
    for glob in check_globs_exist:
        assert len(fnmatch.filter(snapshot.files, glob)) == 1, glob

    return venv


@pytest.mark.parametrize(
    ("layout", "expected_directory"),
    [(PexVenvLayout.FLAT, ""), (PexVenvLayout.VENV, "lib/python*/site-packages/")],
)
def test_layout_venv_and_flat_should_give_plausible_output_for_local_platform(
    layout: PexVenvLayout, expected_directory: str, local_pex: Pex, rule_runner: RuleRunner
) -> None:
    run_and_validate(
        rule_runner,
        PexVenvRequest(
            pex=local_pex, layout=layout, output_path=Path("out/dir"), description="testing"
        ),
        check_globs_exist=(
            f"out/dir/{expected_directory}psycopg2/__init__.py",
            f"out/dir/{expected_directory}first/party.py",
        ),
    )


def test_layout_flat_zipped_should_give_plausible_output_for_local_platform(
    local_pex: Pex, rule_runner: RuleRunner
) -> None:
    venv = run_and_validate(
        rule_runner,
        PexVenvRequest(
            pex=local_pex,
            layout=PexVenvLayout.FLAT_ZIPPED,
            output_path=Path("out/file.zip"),
            description="testing",
        ),
        check_globs_exist=("out/file.zip",),
    )

    contents = rule_runner.request(DigestContents, [venv.digest])
    assert len(contents) == 1
    with zipfile.ZipFile(io.BytesIO(contents[0].content)) as f:
        files = set(f.namelist())
        assert "psycopg2/__init__.py" in files
        assert "first/party.py" in files


def test_layout_flat_zipped_should_require_zip_suffix(
    local_pex: Pex, rule_runner: RuleRunner
) -> None:
    with pytest.raises(
        ExecutionError,
        match="layout=FLAT_ZIPPED requires output_path to end in '\\.zip', but found output_path='out/file\\.other' ending in '\\.other'",
    ):
        run_and_validate(
            rule_runner,
            PexVenvRequest(
                pex=local_pex,
                layout=PexVenvLayout.FLAT_ZIPPED,
                output_path=Path("out/file.other"),
                description="testing",
            ),
            check_globs_exist=(),
        )


def test_platforms_should_choose_appropriate_dependencies_when_possible(
    foreign_pex: Pex, rule_runner: RuleRunner
) -> None:
    # smoke test that platforms are passed through in the right way
    run_and_validate(
        rule_runner,
        PexVenvRequest(
            pex=foreign_pex,
            layout=PexVenvLayout.FLAT,
            output_path=Path("out"),
            platforms=PexPlatforms([WIN_311]),
            description="testing",
        ),
        check_globs_exist=(
            "out/first/party.py",
            "out/psycopg2/__init__.py",
        ),
    )


def test_complete_platforms_should_choose_appropriate_dependencies_when_possible(
    foreign_pex: Pex,
    rule_runner: RuleRunner,
) -> None:
    # smoke test that complete platforms are passed through in the right way
    cp_snapshot = rule_runner.request(
        Snapshot, [CreateDigest([FileContent("cp", content=MAC_310_CP)])]
    )

    run_and_validate(
        rule_runner,
        PexVenvRequest(
            pex=foreign_pex,
            layout=PexVenvLayout.FLAT,
            output_path=Path("out"),
            complete_platforms=CompletePlatforms.from_snapshot(cp_snapshot),
            description="testing",
        ),
        check_globs_exist=(
            "out/first/party.py",
            "out/psycopg2/__init__.py",
        ),
    )


def test_prefix_should_add_path(
    local_pex: Pex,
    rule_runner: RuleRunner,
) -> None:
    run_and_validate(
        rule_runner,
        PexVenvRequest(
            pex=local_pex,
            layout=PexVenvLayout.FLAT,
            prefix="some/prefix",
            output_path=Path("out/dir"),
            description="testing",
        ),
        check_globs_exist=(
            "out/dir/some/prefix/psycopg2/__init__.py",
            "out/dir/some/prefix/first/party.py",
        ),
    )
