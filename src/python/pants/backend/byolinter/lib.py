import itertools
from dataclasses import dataclass
from typing import Mapping, Optional, List

from pants.core.goals.lint import LintTargetsRequest, LintResult
from pants.core.target_types import FileSourceField
from pants.core.util_rules.partitions import PartitionerType
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.env_vars import CompleteEnvironmentVars
from pants.engine.internals.selectors import Get
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.option.option_types import SkipOption
from pants.option.subsystem import Subsystem
from pants.util.logging import LogLevel


@dataclass
class ByoLinter:
    options_scope: str
    name: str
    help: str
    command: str
    file_extensions: List[str]

    def rules(self):
        return build(self)


def build(conf: ByoLinter):
    assert conf.options_scope.isidentifier(), "The options scope must be a valid python identifier"
    subsystem_cls = type(Subsystem)(f'ByoLint_{conf.options_scope}_Subsystem', (Subsystem,), dict(
        options_scope=conf.options_scope,
        skip=SkipOption("lint"),
        name=conf.name,
        help=conf.help,
        _dynamic_subsystem=True,
    ))

    subsystem_cls.__module__ = __name__

    def opt_out(tgt: Target) -> bool:
        source = tgt.get(FileSourceField).value
        return not any(source.endswith(ext) for ext in conf.file_extensions)

    fieldset_cls = type(FieldSet)(f'ByoLint_{conf.options_scope}_FieldSet', (FieldSet,), dict(
        required_fields=(FileSourceField,),
        opt_out=staticmethod(opt_out),
        __annotations__=dict(source=FileSourceField)
    ))
    fieldset_cls.__module__ = __name__
    fieldset_cls = dataclass(frozen=True)(fieldset_cls)

    lintreq_cls = type(LintTargetsRequest)(f'ByoLint_{conf.options_scope}_Request', (LintTargetsRequest,), dict(
        tool_subsystem=subsystem_cls,
        partitioner_type=PartitionerType.DEFAULT_SINGLE_PARTITION,
        field_set_type=fieldset_cls,
    ))
    lintreq_cls.__module__ = __name__

    @rule(canonical_name_suffix=conf.options_scope)
    async def run_ByoLint(
            request: lintreq_cls.Batch,
            complete_env: CompleteEnvironmentVars,
    ) -> LintResult:

        sources = await Get(
            SourceFiles,
            SourceFilesRequest(field_set.source for field_set in request.elements),
        )

        input_digest = sources.snapshot.digest

        import pantsdebug; pantsdebug.settrace_5678()
        process_result = await Get(
            FallibleProcessResult,
            Process(
                argv=(conf.command, *sources.files),
                input_digest=input_digest,
                description=f"Run {conf.name}",
                level=LogLevel.INFO,
                env={**complete_env}
            ),
        )
        return LintResult.create(request, process_result)

    namespace = dict(locals())

    return [
        *collect_rules(namespace),
        *lintreq_cls.rules()
    ]


# def rules():
#     confs = [
#         ByoLintConf(
#             options_scope='byo_shellcheck',
#             name="Shellcheck",
#             help="A shell linter based on your installed shellcheck",
#             command="shellcheck",
#             file_extensions=[".sh"],
#         ),
#         ByoLintConf(
#             options_scope='byo_linters',
#             name="MarkdownLint",
#             help="A markdown linter based on your installed markdown lint.",
#             command="markdownlint",
#             file_extensions=[".md"],
#         )
#     ]
#     return list(itertools.chain.from_iterable(conf.rules() for conf in confs))
