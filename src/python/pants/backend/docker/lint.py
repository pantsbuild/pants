from dataclasses import dataclass

from pants.backend.docker.target_types import DockerImageSources
from pants.core.goals.lint import LintRequest, LintResult, LintResults
from pants.core.util_rules.external_tool import (
    DownloadedExternalTool,
    ExternalToolRequest,
    TemplatedExternalTool,
)
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import Digest, MergeDigests
from pants.engine.platform import Platform
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import BoolField, FieldSet, Target
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


class HadolintTool(TemplatedExternalTool):
    options_scope = "download-hadolint"
    name = "hadolint"
    help = "Hadolint Dockerfile linter (https://github.com/hadolint/hadolint)"

    default_version = "v2.6.0"
    default_url_template = (
        "https://github.com/hadolint/hadolint/releases/download/{version}/hadolint-{platform}"
    )
    default_url_platform_mapping = {
        "darwin": "Darwin-x86_64",
        "linux": "Linux-x86_64",
        "windows": "Windows-x86_64.exe",
    }
    default_known_versions = [
        "v2.6.0|darwin |7d41496bf591f2b9c7daa76d4aa1db04ea97b9e11b44a24a4e404a10aab33686|2392080",
        "v2.6.0|linux  |152e3c3375f26711650d4e11f9e382cf1bdf3f912d7379823e8fac4b1bce88d6|5812840",
        "v2.6.0|windows|f74ed11f5b24c0065bed273625c5a1cef858738393d1cf7fa0c2e163fa3dad9d|5170176",
    ]


class SkipHadolintField(BoolField):
    alias = "skip_hadolint"
    default = False
    help = "If true, don't run hadolint on this target's Dockerfile."


@dataclass(frozen=True)
class HadolintFieldSet(FieldSet):
    required_fields = (DockerImageSources,)

    sources: DockerImageSources

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipHadolintField).value


class HadolintRequest(LintRequest):
    field_set_type = HadolintFieldSet


@rule(desc="Lint using Hadolint")
async def hadolint_lint(request: HadolintRequest, hadolint: HadolintTool) -> LintResults:
    tool, sources = await MultiGet(
        Get(DownloadedExternalTool, ExternalToolRequest, hadolint.get_request(Platform.current)),
        Get(
            SourceFiles, SourceFilesRequest([field_set.sources for field_set in request.field_sets])
        ),
    )

    input_digest = await Get(Digest, MergeDigests((sources.snapshot.digest, tool.digest)))

    result = await Get(
        FallibleProcessResult,
        Process(
            argv=[tool.exe, *sources.snapshot.files],
            input_digest=input_digest,
            description=f"Run `hadolint` on {pluralize(len(sources.snapshot.files), 'Dockerfile')}.",
            level=LogLevel.DEBUG,
        ),
    )

    return LintResults(
        [
            LintResult(
                exit_code=result.exit_code,
                stdout=result.stdout.decode(),
                stderr=result.stderr.decode(),
            )
        ],
        linter_name="hadolint",
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(LintRequest, HadolintRequest),
    ]
