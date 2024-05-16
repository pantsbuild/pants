# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import configparser
from dataclasses import dataclass
from enum import Enum
from io import StringIO
from pathlib import PurePath
from typing import Any, MutableMapping, cast

import toml

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
from pants.core.util_rules.distdir import DistDir
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
from pants.option.global_options import KeepSandboxes
from pants.option.option_types import (
    BoolOption,
    EnumListOption,
    FileOption,
    FloatOption,
    StrListOption,
    StrOption,
)
from pants.source.source_root import AllSourceRoots
from pants.util.logging import LogLevel
from pants.util.strutil import softwrap

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
    LCOV = ("lcov", None)

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
    help_short = "Configuration for Python test coverage measurement."

    default_main = ConsoleScript("coverage")
    default_requirements = ["coverage[toml]>=6.5,<8"]

    register_interpreter_constraints = True

    default_lockfile_resource = ("pants.backend.python.subsystems", "coverage_py.lock")

    filter = StrListOption(
        help=softwrap(
            """
            A list of Python modules or filesystem paths to use in the coverage report, e.g.
            `['helloworld_test', 'helloworld/util/dirutil']`.

            Both modules and directory paths are recursive: any submodules or child paths,
            respectively, will be included.

            If you leave this off, the coverage report will include every file
            in the transitive closure of the address/file arguments; for example, `test ::`
            will include every Python file in your project, whereas
            `test project/app_test.py` will include `app_test.py` and any of its transitive
            dependencies.
            """
        ),
    )
    report = EnumListOption(
        default=[CoverageReportType.CONSOLE],
        help="Which coverage report type(s) to emit.",
    )
    _output_dir = StrOption(
        default=str(PurePath("{distdir}", "coverage", "python")),
        advanced=True,
        help="Path to write the Pytest Coverage report to. Must be relative to the build root.",
    )
    config = FileOption(
        default=None,
        advanced=True,
        help=lambda cls: softwrap(
            f"""
            Path to an INI or TOML config file understood by coverage.py
            (https://coverage.readthedocs.io/en/latest/config.html).

            Setting this option will disable `[{cls.options_scope}].config_discovery`. Use
            this option if the config is located in a non-standard location.
            """
        ),
    )
    config_discovery = BoolOption(
        default=True,
        advanced=True,
        help=lambda cls: softwrap(
            f"""
            If true, Pants will include any relevant config files during runs
            (`.coveragerc`, `setup.cfg`, `tox.ini`, and `pyproject.toml`).

            Use `[{cls.options_scope}].config` instead if your config is in a
            non-standard location.
            """
        ),
    )
    global_report = BoolOption(
        default=False,
        help=softwrap(
            """
            If true, Pants will generate a global coverage report.

            The global report will include all Python source files in the workspace and not just
            those depended on by the tests that were run.
            """
        ),
    )
    fail_under = FloatOption(
        default=None,
        help=softwrap(
            """
            Fail if the total combined coverage percentage for all tests is less than this
            number.

            Use this instead of setting `fail_under` in a coverage.py config file,
            as the config will apply to each test separately, while you typically want this
            to apply to the combined coverage for all tests run.

            Note that you must generate at least one (non-raw) coverage report for this
            check to trigger.

            Note also that if you specify a non-integral value, you must
            also set `[report] precision` properly in the coverage.py config file to make use
            of the decimal places. See https://coverage.readthedocs.io/en/latest/config.html.
            """
        ),
    )

    def output_dir(self, distdir: DistDir) -> PurePath:
        return PurePath(self._output_dir.format(distdir=distdir.relpath))

    @property
    def config_request(self) -> ConfigFilesRequest:
        # Refer to https://coverage.readthedocs.io/en/stable/config.html.
        return ConfigFilesRequest(
            specified=self.config,
            specified_option_name=f"[{self.options_scope}].config",
            discovery=self.config_discovery,
            check_existence=[".coveragerc"],
            check_content={
                "setup.cfg": b"[coverage:",
                "tox.ini": b"[coverage:]",
                "pyproject.toml": b"[tool.coverage",
            },
        )


@dataclass(frozen=True)
class PytestCoverageData(CoverageData):
    addresses: tuple[Address, ...]
    digest: Digest


class PytestCoverageDataCollection(CoverageDataCollection[PytestCoverageData]):
    element_type = PytestCoverageData


@dataclass(frozen=True)
class CoverageConfig:
    digest: Digest
    path: str


class InvalidCoverageConfigError(Exception):
    pass


def _parse_toml_config(fc: FileContent) -> MutableMapping[str, Any]:
    try:
        return toml.loads(fc.content.decode())
    except toml.TomlDecodeError as exc:
        raise InvalidCoverageConfigError(
            softwrap(
                f"""
                Failed to parse the coverage.py config `{fc.path}` as TOML. Please either fix
                the config or update `[coverage-py].config` and/or
                `[coverage-py].config_discovery`.

                Parse error: {repr(exc)}
                """
            )
        )


def _parse_ini_config(fc: FileContent) -> configparser.ConfigParser:
    cp = configparser.ConfigParser()
    try:
        cp.read_string(fc.content.decode())
        return cp
    except configparser.Error as exc:
        raise InvalidCoverageConfigError(
            softwrap(
                f"""
                Failed to parse the coverage.py config `{fc.path}` as INI. Please either fix
                the config or update `[coverage-py].config` and/or `[coverage-py].config_discovery`.

                Parse error: {repr(exc)}
                """
            )
        )


def _update_config(fc: FileContent) -> FileContent:
    if PurePath(fc.path).suffix == ".toml":
        all_config = _parse_toml_config(fc)
        tool = all_config.setdefault("tool", {})
        coverage = tool.setdefault("coverage", {})
        run = coverage.setdefault("run", {})
        run["relative_files"] = True
        if "pytest.pex/*" not in run.get("omit", []):
            run["omit"] = [*run.get("omit", []), "pytest.pex/*"]
        return FileContent(fc.path, toml.dumps(all_config).encode())

    cp = _parse_ini_config(fc)
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


def get_branch_value_from_config(fc: FileContent) -> bool:
    # Note that coverage's default value for the branch setting is False, which we mirror here.
    if PurePath(fc.path).suffix == ".toml":
        all_config = _parse_toml_config(fc)
        return bool(
            all_config.get("tool", {}).get("coverage", {}).get("run", {}).get("branch", False)
        )

    cp = _parse_ini_config(fc)
    run_section = "coverage:run" if fc.path in ("tox.ini", "setup.cfg") else "run"
    if not cp.has_section(run_section):
        return False
    return cp.getboolean(run_section, "branch", fallback=False)


def get_namespace_value_from_config(fc: FileContent) -> bool:
    if PurePath(fc.path).suffix == ".toml":
        all_config = _parse_toml_config(fc)
        return bool(
            all_config.get("tool", {})
            .get("coverage", {})
            .get("report", {})
            .get("include_namespace_packages", False)
        )

    cp = _parse_ini_config(fc)
    report_section = "coverage:report" if fc.path in ("tox.ini", "setup.cfg") else "report"
    if not cp.has_section(report_section):
        return False
    return cp.getboolean(report_section, "include_namespace_packages", fallback=False)


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
        # We know that .coveragerc doesn't exist, so it's fine to create one.
        file_content = FileContent(".coveragerc", stream.getvalue().encode())
    digest = await Get(Digest, CreateDigest([file_content]))
    return CoverageConfig(digest, file_content.path)


@dataclass(frozen=True)
class CoverageSetup:
    pex: VenvPex


@rule
async def setup_coverage(coverage: CoverageSubsystem) -> CoverageSetup:
    pex = await Get(VenvPex, PexRequest, coverage.to_pex_request())
    return CoverageSetup(pex)


@dataclass(frozen=True)
class MergedCoverageData:
    coverage_data: Digest
    addresses: tuple[Address, ...]


@rule(desc="Merge Pytest coverage data", level=LogLevel.DEBUG)
async def merge_coverage_data(
    data_collection: PytestCoverageDataCollection,
    coverage_setup: CoverageSetup,
    coverage_config: CoverageConfig,
    coverage: CoverageSubsystem,
    source_roots: AllSourceRoots,
) -> MergedCoverageData:
    if len(data_collection) == 1 and not coverage.global_report:
        coverage_data = data_collection[0]
        return MergedCoverageData(coverage_data.digest, coverage_data.addresses)

    coverage_digest_gets = []
    coverage_data_file_paths = []
    addresses: list[Address] = []
    for data in data_collection:
        path_prefix = data.addresses[0].path_safe_spec
        if len(data.addresses) > 1:
            path_prefix = f"{path_prefix}+{len(data.addresses)-1}-others"

        # We prefix each .coverage file with its corresponding address to avoid collisions.
        coverage_digest_gets.append(Get(Digest, AddPrefix(data.digest, prefix=path_prefix)))
        coverage_data_file_paths.append(f"{path_prefix}/.coverage")
        addresses.extend(data.addresses)

    if coverage.global_report:
        # It's important to set the `branch` value in the empty base report to the value it will
        # have when running on real inputs, so that the reports are of the same type, and can be
        # merged successfully. Otherwise we may get "Can't combine arc data with line data" errors.
        # See https://github.com/pantsbuild/pants/issues/14542 .
        config_contents = await Get(DigestContents, Digest, coverage_config.digest)
        branch = get_branch_value_from_config(config_contents[0]) if config_contents else False
        namespace_packages = (
            get_namespace_value_from_config(config_contents[0]) if config_contents else False
        )
        global_coverage_base_dir = PurePath("__global_coverage__")
        global_coverage_config_path = global_coverage_base_dir / "pyproject.toml"
        global_coverage_config_content = toml.dumps(
            {
                "tool": {
                    "coverage": {
                        "run": {
                            "relative_files": True,
                            "source": [source_root.path for source_root in source_roots],
                            "branch": branch,
                        },
                        "report": {
                            "include_namespace_packages": namespace_packages,
                        },
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
            # We tell combine to keep the original input files, to aid debugging in the sandbox.
            argv=("combine", "--keep", *sorted(coverage_data_file_paths)),
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
    keep_sandboxes: KeepSandboxes,
    distdir: DistDir,
) -> CoverageReports:
    """Takes all Python test results and generates a single coverage report."""
    transitive_targets = await Get(
        TransitiveTargets, TransitiveTargetsRequest(merged_coverage_data.addresses)
    )
    sources = await Get(
        PythonSourceFiles,
        # Coverage sometimes includes non-Python files in its `.coverage` data, so we
        # include resources here. We don't include files because relocated_files targets
        # may cause digest merge collisions. So anything you compute coverage over must
        # be a source file or a resource.
        PythonSourceFilesRequest(transitive_targets.closure, include_resources=True),
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
    output_dir: PurePath = coverage_subsystem.output_dir(distdir)
    for report_type in coverage_subsystem.report:
        if report_type == CoverageReportType.RAW:
            coverage_reports.append(
                FilesystemCoverageReport(
                    # We don't know yet if the coverage is sufficient, so we let some other report
                    # trigger the failure if necessary.
                    coverage_insufficient=False,
                    report_type=CoverageReportType.RAW.value,
                    result_snapshot=result_snapshot,
                    directory_to_materialize_to=output_dir,
                    report_file=output_dir / ".coverage",
                )
            )
            continue

        report_types.append(report_type)
        output_file = (
            f"coverage.{report_type.value}"
            if report_type
            in {CoverageReportType.XML, CoverageReportType.JSON, CoverageReportType.LCOV}
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
                keep_sandboxes=keep_sandboxes,
            )

    # In practice if one result triggers --fail-under, they all will, but no need to rely on that.
    result_exit_codes = tuple(res.exit_code for res in results)
    result_stdouts = tuple(res.stdout for res in results)
    result_snapshots = await MultiGet(Get(Snapshot, Digest, res.output_digest) for res in results)

    coverage_reports.extend(
        _get_coverage_report(output_dir, report_type, exit_code != 0, stdout, snapshot)
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

    try:
        report_file = {
            CoverageReportType.HTML: output_dir / "htmlcov" / "index.html",
            CoverageReportType.XML: output_dir / "coverage.xml",
            CoverageReportType.JSON: output_dir / "coverage.json",
            CoverageReportType.LCOV: output_dir / "coverage.lcov",
        }[report_type]
    except KeyError:
        raise ValueError(f"Invalid coverage report type: {report_type}") from None

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
    ]
