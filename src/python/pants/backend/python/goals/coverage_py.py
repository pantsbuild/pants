# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import configparser
from dataclasses import dataclass
from enum import Enum
from io import StringIO
from pathlib import PurePath
from typing import cast

import toml

from pants.backend.python.goals.lockfile import PythonLockfileRequest, PythonToolLockfileSentinel
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.backend.python.util_rules.python_sources import (
    PythonSourceFiles,
    PythonSourceFilesRequest,
)
from pants.core.goals.test import (
    ConsoleCoverageReport,
    CoverageData,
    CoverageDataCollection,
    CoverageReport,
    CoverageReports,
    FilesystemCoverageReport,
)
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.engine.addresses import Address
from pants.engine.fs import (
    EMPTY_DIGEST,
    AddPrefix,
    CreateDigest,
    Digest,
    DigestContents,
    FileContent,
    MergeDigests,
    PathGlobs,
    Snapshot,
)
from pants.engine.process import FallibleProcessResult, ProcessExecutionFailure, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import TransitiveTargets, TransitiveTargetsRequest
from pants.engine.unions import UnionRule
from pants.option.custom_types import file_option
from pants.option.global_options import GlobalOptions
from pants.source.source_root import AllSourceRoots
from pants.util.docutil import git_url
from pants.util.logging import LogLevel

"""
An overview:

Step 1: Run each test with the appropriate `--cov` arguments.
In `python_test_runner.py`, we pass options so that the pytest-cov plugin runs and records which
lines were encountered in the test. For each test, it will save a `.coverage` file (SQLite DB
format).

Step 2: Merge the results with `coverage combine`.
We now have a bunch of individual `PytestCoverageData` values, each with their own `.coverage` file.
We run `coverage combine` to convert this into a single `.coverage` file.

Step 3: Generate the report with `coverage {html,xml,console}`.
All the files in the single merged `.coverage` file are still stripped, and we want to generate a
report with the source roots restored. Coverage requires that the files it's reporting on be present
when it generates the report, so we populate all the source files.

Step 4: `test.py` outputs the final report.
"""


class CoverageReportType(Enum):
    CONSOLE = ("console", "report")
    XML = ("xml", None)
    HTML = ("html", None)
    RAW = ("raw", None)
    JSON = ("json", None)

    _report_name: str

    def __new__(cls, value: str, report_name: str | None = None) -> CoverageReportType:
        member: CoverageReportType = object.__new__(cls)
        member._value_ = value
        member._report_name = report_name if report_name is not None else value
        return member

    @property
    def report_name(self) -> str:
        return self._report_name

    @property
    def value(self) -> str:
        return cast(str, super().value)


class CoverageSubsystem(PythonToolBase):
    options_scope = "coverage-py"
    help = "Configuration for Python test coverage measurement."

    default_version = "coverage[toml]>=5.5,<5.6"
    default_main = ConsoleScript("coverage")

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.6,<4"]

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.python.subsystems", "coverage_py_lockfile.txt")
    default_lockfile_path = "src/python/pants/backend/python/subsystems/coverage_py_lockfile.txt"
    default_lockfile_url = git_url(default_lockfile_path)

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--filter",
            type=list,
            member_type=str,
            default=None,
            help=(
                "A list of Python modules or filesystem paths to use in the coverage report, e.g. "
                "`['helloworld_test', 'helloworld/util/dirutil'].\n\nBoth modules and directory "
                "paths are recursive: any submodules or child paths, respectively, will be "
                "included.\n\nIf you leave this off, the coverage report will include every file "
                "in the transitive closure of the address/file arguments; for example, `test ::` "
                "will include every Python file in your project, whereas "
                "`test project/app_test.py` will include `app_test.py` and any of its transitive "
                "dependencies."
            ),
        )
        register(
            "--report",
            type=list,
            member_type=CoverageReportType,
            default=[CoverageReportType.CONSOLE],
            help="Which coverage report type(s) to emit.",
        )
        register(
            "--output-dir",
            type=str,
            default=str(PurePath("dist", "coverage", "python")),
            advanced=True,
            help="Path to write the Pytest Coverage report to. Must be relative to build root.",
        )
        register(
            "--config",
            type=file_option,
            default=None,
            advanced=True,
            help=(
                "Path to an INI or TOML config file understood by coverage.py "
                "(https://coverage.readthedocs.io/en/stable/config.html).\n\n"
                f"Setting this option will disable `[{cls.options_scope}].config_discovery`. Use "
                f"this option if the config is located in a non-standard location."
            ),
        )
        register(
            "--config-discovery",
            type=bool,
            default=True,
            advanced=True,
            help=(
                "If true, Pants will include any relevant config files during runs "
                "(`.coveragerc`, `setup.cfg`, `tox.ini`, and `pyproject.toml`)."
                f"\n\nUse `[{cls.options_scope}].config` instead if your config is in a "
                f"non-standard location."
            ),
        )
        register(
            "--global-report",
            type=bool,
            default=False,
            help=(
                "If true, Pants will generate a global coverage report.\n\nThe global report will "
                "include all Python source files in the workspace and not just those depended on "
                "by the tests that were run."
            ),
        )
        register(
            "--fail-under",
            type=float,
            default=None,
            help=(
                "Fail if the total combined coverage percentage for all tests is less than this "
                "number.\n\nUse this instead of setting fail_under in a coverage.py config file, "
                "as the config will apply to each test separately, while you typically want this "
                "to apply to the combined coverage for all tests run."
                "\n\nNote that you must generate at least one (non-raw) coverage report for this "
                "check to trigger.\n\nNote also that if you specify a non-integral value, you must "
                "also set [report] precision properly in the coverage.py config file to make use "
                "of the decimal places. See https://coverage.readthedocs.io/en/latest/config.html ."
            ),
        )

    @property
    def filter(self) -> tuple[str, ...]:
        return tuple(self.options.filter)

    @property
    def reports(self) -> tuple[CoverageReportType, ...]:
        return tuple(self.options.report)

    @property
    def output_dir(self) -> PurePath:
        return PurePath(self.options.output_dir)

    @property
    def config(self) -> str | None:
        return cast("str | None", self.options.config)

    @property
    def config_request(self) -> ConfigFilesRequest:
        # Refer to https://coverage.readthedocs.io/en/stable/config.html.
        return ConfigFilesRequest(
            specified=self.config,
            specified_option_name=f"[{self.options_scope}].config",
            discovery=cast(bool, self.options.config_discovery),
            check_existence=[".coveragerc"],
            check_content={
                "setup.cfg": b"[coverage:",
                "tox.ini": b"[coverage:]",
                "pyproject.toml": b"[tool.coverage",
            },
        )

    @property
    def global_report(self) -> bool:
        return cast(bool, self.options.global_report)

    @property
    def fail_under(self) -> int:
        return cast(int, self.options.fail_under)


class CoveragePyLockfileSentinel(PythonToolLockfileSentinel):
    options_scope = CoverageSubsystem.options_scope


@rule
def setup_coverage_lockfile(
    _: CoveragePyLockfileSentinel, coverage: CoverageSubsystem
) -> PythonLockfileRequest:
    return PythonLockfileRequest.from_tool(coverage)


@dataclass(frozen=True)
class PytestCoverageData(CoverageData):
    address: Address
    digest: Digest


class PytestCoverageDataCollection(CoverageDataCollection):
    element_type = PytestCoverageData


@dataclass(frozen=True)
class CoverageConfig:
    digest: Digest
    path: str


def _validate_and_update_config(
    coverage_config: configparser.ConfigParser, config_path: str | None
) -> None:
    if not coverage_config.has_section("run"):
        coverage_config.add_section("run")
    run_section = coverage_config["run"]
    relative_files_str = run_section.get("relative_files", "True")
    if relative_files_str.lower() != "true":
        raise ValueError(
            "relative_files under the 'run' section must be set to True in the config "
            f"file {config_path}"
        )
    coverage_config.set("run", "relative_files", "True")
    omit_elements = [em for em in run_section.get("omit", "").split("\n")] or ["\n"]
    if "pytest.pex/*" not in omit_elements:
        omit_elements.append("pytest.pex/*")
    run_section["omit"] = "\n".join(omit_elements)


class InvalidCoverageConfigError(Exception):
    pass


def _update_config(fc: FileContent) -> FileContent:
    if PurePath(fc.path).suffix == ".toml":
        try:
            all_config = toml.loads(fc.content.decode())
        except toml.TomlDecodeError as exc:
            raise InvalidCoverageConfigError(
                f"Failed to parse the coverage.py config `{fc.path}` as TOML. Please either fix "
                f"the config or update `[coverage-py].config` and/or "
                f"`[coverage-py].config_discovery`.\n\nParse error: {repr(exc)}"
            )
        tool = all_config.setdefault("tool", {})
        coverage = tool.setdefault("coverage", {})
        run = coverage.setdefault("run", {})
        run["relative_files"] = True
        if "pytest.pex/*" not in run.get("omit", []):
            run["omit"] = [*run.get("omit", []), "pytest.pex/*"]
        return FileContent(fc.path, toml.dumps(all_config).encode())

    cp = configparser.ConfigParser()
    try:
        cp.read_string(fc.content.decode())
    except configparser.Error as exc:
        raise InvalidCoverageConfigError(
            f"Failed to parse the coverage.py config `{fc.path}` as INI. Please either fix "
            f"the config or update `[coverage-py].config` and/or `[coverage-py].config_discovery`."
            f"\n\nParse error: {repr(exc)}"
        )
    run_section = "coverage:run" if fc.path in ("tox.ini", "setup.cfg") else "run"
    if not cp.has_section(run_section):
        cp.add_section(run_section)
    cp.set(run_section, "relative_files", "True")
    omit_elements = cp[run_section].get("omit", "").split("\n") or ["\n"]
    if "pytest.pex/*" not in omit_elements:
        omit_elements.append("pytest.pex/*")
    cp.set(run_section, "omit", "\n".join(omit_elements))
    stream = StringIO()
    cp.write(stream)
    return FileContent(fc.path, stream.getvalue().encode())


@rule
async def create_or_update_coverage_config(coverage: CoverageSubsystem) -> CoverageConfig:
    config_files = await Get(ConfigFiles, ConfigFilesRequest, coverage.config_request)
    if config_files.snapshot.files:
        digest_contents = await Get(DigestContents, Digest, config_files.snapshot.digest)
        file_content = _update_config(digest_contents[0])
    else:
        cp = configparser.ConfigParser()
        cp.add_section("run")
        cp.set("run", "relative_files", "True")
        cp.set("run", "omit", "\npytest.pex/*")
        stream = StringIO()
        cp.write(stream)
        file_content = FileContent(".coveragerc", stream.getvalue().encode())
    digest = await Get(Digest, CreateDigest([file_content]))
    return CoverageConfig(digest, file_content.path)


@dataclass(frozen=True)
class CoverageSetup:
    pex: VenvPex


@rule
async def setup_coverage(coverage: CoverageSubsystem) -> CoverageSetup:
    pex = await Get(
        VenvPex,
        PexRequest(
            output_filename="coverage.pex",
            internal_only=True,
            requirements=coverage.pex_requirements(),
            interpreter_constraints=coverage.interpreter_constraints,
            main=coverage.main,
        ),
    )
    return CoverageSetup(pex)


@dataclass(frozen=True)
class MergedCoverageData:
    coverage_data: Digest
    addresses: tuple[Address, ...]


@rule(desc="Merge Pytest coverage data", level=LogLevel.DEBUG)
async def merge_coverage_data(
    data_collection: PytestCoverageDataCollection,
    coverage_setup: CoverageSetup,
    coverage: CoverageSubsystem,
    source_roots: AllSourceRoots,
) -> MergedCoverageData:
    if len(data_collection) == 1 and not coverage.global_report:
        coverage_data = data_collection[0]
        return MergedCoverageData(coverage_data.digest, (coverage_data.address,))

    coverage_digest_gets = []
    coverage_data_file_paths = []
    addresses = []
    for data in data_collection:
        # We prefix each .coverage file with its corresponding address to avoid collisions.
        coverage_digest_gets.append(
            Get(Digest, AddPrefix(data.digest, prefix=data.address.path_safe_spec))
        )
        coverage_data_file_paths.append(f"{data.address.path_safe_spec}/.coverage")
        addresses.append(data.address)

    if coverage.global_report:
        global_coverage_base_dir = PurePath("__global_coverage__")

        global_coverage_config_path = global_coverage_base_dir / "pyproject.toml"
        global_coverage_config_content = toml.dumps(
            {
                "tool": {
                    "coverage": {
                        "run": {
                            "relative_files": True,
                            "source": list(source_root.path for source_root in source_roots),
                        }
                    }
                }
            }
        ).encode()

        no_op_exe_py_path = global_coverage_base_dir / "no-op-exe.py"

        all_sources_digest, no_op_exe_py_digest, global_coverage_config_digest = await MultiGet(
            Get(
                Digest,
                PathGlobs(globs=[f"{source_root.path}/**/*.py" for source_root in source_roots]),
            ),
            Get(Digest, CreateDigest([FileContent(path=str(no_op_exe_py_path), content=b"")])),
            Get(
                Digest,
                CreateDigest(
                    [
                        FileContent(
                            path=str(global_coverage_config_path),
                            content=global_coverage_config_content,
                        ),
                    ]
                ),
            ),
        )
        extra_sources_digest = await Get(
            Digest, MergeDigests((all_sources_digest, no_op_exe_py_digest))
        )
        input_digest = await Get(
            Digest, MergeDigests((extra_sources_digest, global_coverage_config_digest))
        )
        result = await Get(
            ProcessResult,
            VenvPexProcess(
                coverage_setup.pex,
                argv=("run", "--rcfile", str(global_coverage_config_path), str(no_op_exe_py_path)),
                input_digest=input_digest,
                output_files=(".coverage",),
                description="Create base global Pytest coverage report.",
                level=LogLevel.DEBUG,
            ),
        )
        coverage_digest_gets.append(
            Get(
                Digest, AddPrefix(digest=result.output_digest, prefix=str(global_coverage_base_dir))
            )
        )
        coverage_data_file_paths.append(str(global_coverage_base_dir / ".coverage"))
    else:
        extra_sources_digest = EMPTY_DIGEST

    input_digest = await Get(Digest, MergeDigests(await MultiGet(coverage_digest_gets)))
    result = await Get(
        ProcessResult,
        VenvPexProcess(
            coverage_setup.pex,
            argv=("combine", *sorted(coverage_data_file_paths)),
            input_digest=input_digest,
            output_files=(".coverage",),
            description=f"Merge {len(coverage_data_file_paths)} Pytest coverage reports.",
            level=LogLevel.DEBUG,
        ),
    )
    return MergedCoverageData(
        await Get(Digest, MergeDigests((result.output_digest, extra_sources_digest))),
        tuple(addresses),
    )


@rule(desc="Generate Pytest coverage reports", level=LogLevel.DEBUG)
async def generate_coverage_reports(
    merged_coverage_data: MergedCoverageData,
    coverage_setup: CoverageSetup,
    coverage_config: CoverageConfig,
    coverage_subsystem: CoverageSubsystem,
    global_options: GlobalOptions,
) -> CoverageReports:
    """Takes all Python test results and generates a single coverage report."""
    transitive_targets = await Get(
        TransitiveTargets, TransitiveTargetsRequest(merged_coverage_data.addresses)
    )
    sources = await Get(
        PythonSourceFiles,
        # Coverage sometimes includes non-Python files in its `.coverage` data. We need to
        # ensure that they're present when generating the report. We include all the files included
        # by `pytest_runner.py`.
        PythonSourceFilesRequest(
            transitive_targets.closure, include_files=True, include_resources=True
        ),
    )
    input_digest = await Get(
        Digest,
        MergeDigests(
            (
                merged_coverage_data.coverage_data,
                coverage_config.digest,
                sources.source_files.snapshot.digest,
            )
        ),
    )

    pex_processes = []
    report_types = []
    result_snapshot = await Get(Snapshot, Digest, merged_coverage_data.coverage_data)
    coverage_reports: list[CoverageReport] = []
    for report_type in coverage_subsystem.reports:
        if report_type == CoverageReportType.RAW:
            coverage_reports.append(
                FilesystemCoverageReport(
                    # We don't know yet if the coverage is sufficient, so we let some other report
                    # trigger the failure if necessary.
                    coverage_insufficient=False,
                    report_type=CoverageReportType.RAW.value,
                    result_snapshot=result_snapshot,
                    directory_to_materialize_to=coverage_subsystem.output_dir,
                    report_file=coverage_subsystem.output_dir / ".coverage",
                )
            )
            continue

        report_types.append(report_type)
        output_file = (
            f"coverage.{report_type.value}"
            if report_type in {CoverageReportType.XML, CoverageReportType.JSON}
            else None
        )
        args = [report_type.report_name, f"--rcfile={coverage_config.path}"]
        if coverage_subsystem.fail_under is not None:
            args.append(f"--fail-under={coverage_subsystem.fail_under}")
        pex_processes.append(
            VenvPexProcess(
                coverage_setup.pex,
                argv=tuple(args),
                input_digest=input_digest,
                output_directories=("htmlcov",) if report_type == CoverageReportType.HTML else None,
                output_files=(output_file,) if output_file else None,
                description=f"Generate Pytest {report_type.report_name} coverage report.",
                level=LogLevel.DEBUG,
            )
        )
    results = await MultiGet(
        Get(FallibleProcessResult, VenvPexProcess, process) for process in pex_processes
    )
    for proc, res in zip(pex_processes, results):
        if res.exit_code not in {0, 2}:
            # coverage.py uses exit code 2 if --fail-under triggers, in which case the
            # reports are still generated.
            raise ProcessExecutionFailure(
                res.exit_code,
                res.stdout,
                res.stderr,
                proc.description,
                local_cleanup=global_options.options.process_execution_local_cleanup,
            )

    # In practice if one result triggers --fail-under, they all will, but no need to rely on that.
    result_exit_codes = tuple(res.exit_code for res in results)
    result_stdouts = tuple(res.stdout for res in results)
    result_snapshots = await MultiGet(Get(Snapshot, Digest, res.output_digest) for res in results)

    coverage_reports.extend(
        _get_coverage_report(
            coverage_subsystem.output_dir, report_type, exit_code != 0, stdout, snapshot
        )
        for (report_type, exit_code, stdout, snapshot) in zip(
            report_types, result_exit_codes, result_stdouts, result_snapshots
        )
    )

    return CoverageReports(tuple(coverage_reports))


def _get_coverage_report(
    output_dir: PurePath,
    report_type: CoverageReportType,
    coverage_insufficient: bool,
    result_stdout: bytes,
    result_snapshot: Snapshot,
) -> CoverageReport:
    if report_type == CoverageReportType.CONSOLE:
        return ConsoleCoverageReport(coverage_insufficient, result_stdout.decode())

    report_file: PurePath | None
    if report_type == CoverageReportType.HTML:
        report_file = output_dir / "htmlcov" / "index.html"
    elif report_type == CoverageReportType.XML:
        report_file = output_dir / "coverage.xml"
    elif report_type == CoverageReportType.JSON:
        report_file = output_dir / "coverage.json"
    else:
        raise ValueError(f"Invalid coverage report type: {report_type}")

    return FilesystemCoverageReport(
        coverage_insufficient=coverage_insufficient,
        report_type=report_type.value,
        result_snapshot=result_snapshot,
        directory_to_materialize_to=output_dir,
        report_file=report_file,
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(CoverageDataCollection, PytestCoverageDataCollection),
        UnionRule(PythonToolLockfileSentinel, CoveragePyLockfileSentinel),
    ]
