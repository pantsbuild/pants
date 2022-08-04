# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""
Helper to rapidly incorporate Linters into pants.
TODO:
- parse output ?
"""
import functools
from dataclasses import dataclass
from typing import Callable, Iterable, Optional, Tuple, Type

from pants.backend.python.goals.export import ExportPythonTool, ExportPythonToolSentinel
from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.backend.python.subsystems.python_tool_base import ExportToolOption, PythonToolBase
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import PythonSourceField
from pants.backend.python.util_rules.pex import Pex, PexProcess, PexRequest
from pants.core.goals.generate_lockfiles import DEFAULT_TOOL_LOCKFILE, GenerateToolLockfileSentinel
from pants.core.goals.lint import LintResult, LintResults, LintTargetsRequest
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.internals.native_engine import Digest, MergeDigests
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import SubsystemRule, rule
from pants.engine.target import Dependencies, FieldSet
from pants.engine.unions import UnionRule
from pants.option.option_types import ArgsListOption, BoolOption, FileOption, SkipOption
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize, softwrap


class MetalintTool(PythonToolBase):
    args: ArgsListOption

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.7"]

    export = ExportToolOption()

    register_lockfile = True
    default_lockfile_resource = ("", "")  # shim
    default_lockfile_url = "hihello"  # shim

    skip = SkipOption("lint")

    config = FileOption(
        "--config",
        default=None,
        advanced=True,
        help=lambda cls: softwrap(
            f"""
            Path to a config file for {cls.options_scope}
            """
        ),
    )

    config_discovery = BoolOption(
        "--config-discovery",
        default=True,
        advanced=True,
        help=lambda cls: softwrap(
            """
            If true, Pants will include any relevant config files during
            runs, as defined by the `config_request` function. By default
            pulls in `pyproject.toml`.

            Use `[{cls.options_scope}].config` instead if your config is in a
            non-standard location.
            """
        ),
    )

    @property
    def lockfile(self) -> str:
        shim_lockfile = f"{self.options_scope}.lock"
        if not self._lockfile or self._lockfile == DEFAULT_TOOL_LOCKFILE:
            return shim_lockfile
        return self._lockfile

    def config_request(self) -> ConfigFilesRequest:
        return ConfigFilesRequest(
            specified=self.config,
            specified_option_name=f"[{self.options_scope}].config",
            discovery=self.config_discovery,
            check_existence="pyproject.toml",  # default to pull in pyproject.toml, since that's probably expected
        )


@functools.lru_cache()  # functools.cache is python 3.8, and doesn't have a maxsize
def make_export_rules(
    python_tool: Type[MetalintTool],
) -> Tuple[Type[ExportPythonToolSentinel], Callable]:
    class MetalintExportSentinel(ExportPythonToolSentinel):
        ...

    @rule(level=LogLevel.DEBUG)
    def metalint_export(
        _: MetalintExportSentinel,
        tool: python_tool,  # type: ignore[valid-type]  # python_tool: Type[MetalintTool]
    ) -> ExportPythonTool:
        tool_: MetalintTool = tool  # mypy shenanigans
        return ExportPythonTool(
            resolve_name=tool_.options_scope,
            pex_request=tool_.to_pex_request(),
        )

    return MetalintExportSentinel, metalint_export


@functools.lru_cache()
def make_lockfile_rules(
    python_tool: Type[MetalintTool],
) -> Tuple[Type[GenerateToolLockfileSentinel], Callable]:
    class MetalintGenerateToolLockfileSentinel(GenerateToolLockfileSentinel):
        resolve_name = python_tool.options_scope

    @rule(level=LogLevel.DEBUG)
    def metalint_lockfile(
        _: MetalintGenerateToolLockfileSentinel,
        tool: python_tool,  # type: ignore[valid-type]  # python_tool: Type[MetalintTool]
        python_setup: PythonSetup,
    ) -> GeneratePythonLockfile:
        return GeneratePythonLockfile.from_tool(
            tool, use_pex=python_setup.generate_lockfiles_with_pex
        )

    return MetalintGenerateToolLockfileSentinel, metalint_lockfile


@dataclass(frozen=True)
class Metalint:
    tool: Type[PythonToolBase]
    fs: Type[FieldSet]
    lint_req: Type[LintTargetsRequest]
    export_sentinel: Type[ExportPythonToolSentinel]
    export_rule: Callable
    lockfile_sentinel: Type[GenerateToolLockfileSentinel]
    lockfile_rule: Callable
    run_rule: Callable

    def rules(self):
        return [
            SubsystemRule(self.tool),
            UnionRule(LintTargetsRequest, self.lint_req),
            self.export_rule,
            UnionRule(ExportPythonToolSentinel, self.export_sentinel),
            self.lockfile_rule,
            UnionRule(GenerateToolLockfileSentinel, self.lockfile_sentinel),
            self.run_rule,
        ]


ArgvMaker = Callable[[MetalintTool, Tuple[str, ...]], Iterable[str]]


def no_argv(tool: MetalintTool, files: Tuple[str, ...]):
    """Helper for tools that just run without any args."""
    return []


def files_argv(tool: MetalintTool, files: Tuple[str, ...]):
    """Helper for tools that just take a list of files to run against."""
    return files


def make_linter(
    python_tool: Type[MetalintTool],
    linter_name,
    argv_maker: ArgvMaker,
    _metalint_field_set: Optional[Type[FieldSet]] = None,
    _metalint_request: Optional[Type[LintTargetsRequest]] = None,
):

    metalint_field_set: Type[FieldSet]
    if not _metalint_field_set:

        @dataclass(frozen=True)
        class MetalintFieldSet(FieldSet):
            required_fields = (PythonSourceField,)

            sources: PythonSourceField
            dependencies: Dependencies

        metalint_field_set = MetalintFieldSet
    else:
        metalint_field_set = _metalint_field_set

    metalint_request: Type[LintTargetsRequest]
    if not _metalint_request:

        class MetalintRequest(LintTargetsRequest):
            field_set_type = metalint_field_set
            name = linter_name

        metalint_request = MetalintRequest
    else:
        metalint_request = _metalint_request

    MetalintExportSentinel, metalint_export = make_export_rules(python_tool)

    MetalintGenerateToolLockfileSentinel, metalint_lockfile = make_lockfile_rules(python_tool)

    @rule(level=LogLevel.DEBUG)
    async def run_metalint(
        request: metalint_request,  # type: ignore[valid-type]  # actually Type[LintTargetsRequest]
        metalint: python_tool,  # type: ignore[valid-type]  # actually Type[MetalintTool]
    ) -> LintResults:
        request_: LintTargetsRequest = request  # mypy shenanigans
        metalint_: MetalintTool = metalint  # mypy shenanigans
        if metalint_.skip:
            return LintResults([], linter_name=request_.name)

        metalint_pex = Get(
            Pex,
            PexRequest(
                output_filename=f"{linter_name}.pex",
                internal_only=True,
                requirements=metalint_.pex_requirements(),
                interpreter_constraints=metalint_.interpreter_constraints,
                main=metalint_.main,
            ),
        )

        sources_request = Get(
            SourceFiles,
            SourceFilesRequest(field_set.sources for field_set in request_.field_sets),
        )

        config_files_get = Get(
            ConfigFiles,
            ConfigFilesRequest,
            metalint_.config_request(),
        )

        downloaded_metalint, sources, config_files = await MultiGet(
            metalint_pex, sources_request, config_files_get
        )

        input_digest = await Get(
            Digest,
            MergeDigests(
                (
                    downloaded_metalint.digest,
                    sources.snapshot.digest,
                    config_files.snapshot.digest,
                )
            ),
        )

        argv = argv_maker(metalint_, sources.snapshot.files)
        process_result = await Get(
            FallibleProcessResult,
            PexProcess(
                downloaded_metalint,
                argv=argv,
                input_digest=input_digest,
                description=f"Run {linter_name} on {pluralize(len(request_.field_sets), 'file')}.",
                level=LogLevel.DEBUG,
            ),
        )
        result = LintResult.from_fallible_process_result(process_result)
        return LintResults([result], linter_name=request_.name)

    return Metalint(
        python_tool,
        metalint_field_set,
        metalint_request,
        MetalintExportSentinel,
        metalint_export,
        MetalintGenerateToolLockfileSentinel,
        metalint_lockfile,
        run_metalint,
    )
