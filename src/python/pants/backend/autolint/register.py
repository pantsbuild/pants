from dataclasses import dataclass
from typing import Mapping, Optional

from pants.core.goals.lint import LintTargetsRequest, LintResult
from pants.core.target_types import FileSourceField
from pants.core.util_rules.partitions import PartitionerType
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.internals.selectors import Get
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import collect_rules, rule
from pants.engine.target import FieldSet
from pants.option.option_types import SkipOption
from pants.option.subsystem import Subsystem
from pants.util.logging import LogLevel


# class AlternativeSubsystem(Subsystem):
#     options_scope = "alt"
#     skip = SkipOption("lint")
#     name = "AutoLint"
#     help = "An experimental simplified lint"


import inspect
# import pantsdebug; pantsdebug.settrace_5678()
# src_lines, k = inspect.getsourcelines(AutoLintSubsystem)
# print(srclines[0], k)

#
# @dataclass(frozen=True)
# class AutoLintFieldSet(FieldSet):
#     required_fields = (FileSourceField,)
#     source: FileSourceField

# class AutoLintRequest(LintTargetsRequest):
#     tool_subsystem = AutoLintSubsystem
#     # partitioner_type = PartitionerType.DEFAULT_ONE_PARTITION_PER_INPUT
#     partitioner_type = PartitionerType.DEFAULT_SINGLE_PARTITION
#     field_set_type = AutoLintFieldSet


def target_types():
    return []


@dataclass
class AutoLintConf:
    options_scope: str
    name: str
    help: str
    command: str
    extra_env: Optional[Mapping[str, str]] = None


_shellcheck = AutoLintConf(
    options_scope='autoshellcheck',
    name="Shellcheck",
    help="A shell linter based on your installed shellcheck",
    command="/opt/homebrew/bin/shellcheck",
)


_markdownlint = AutoLintConf(
    options_scope='automarkdownlint',
    name="MarkdownLint",
    help="A markdown linter based on your installed markdown lint.",
    command="/opt/homebrew/bin/markdownlint",
    extra_env={"PATH": "/opt/homebrew/bin/"}
)


def build(conf: AutoLintConf):
    assert conf.options_scope.isidentifier(), "The options scope must be a valid python identifier"
    subsystem_cls = type(Subsystem)(f'AutoLint_{conf.options_scope}_Subsystem', (Subsystem,), dict(
        options_scope=conf.options_scope,
        skip=SkipOption("lint"),
        name=conf.name,
        help=conf.help,
        _dynamic_subsystem=True,
    ))

    subsystem_cls.__module__ = __name__

    fieldset_cls = type(FieldSet)(f'AutoLint_{conf.options_scope}_FieldSet', (FieldSet,), dict(
        required_fields=(FileSourceField,),
        __annotations__=dict(source=FileSourceField)
    ))
    fieldset_cls.__module__ = __name__
    fieldset_cls = dataclass(frozen=True)(fieldset_cls)

    lintreq_cls = type(LintTargetsRequest)(f'AutoLint_{conf.options_scope}_Request', (LintTargetsRequest,), dict(
        tool_subsystem=subsystem_cls,
        partitioner_type=PartitionerType.DEFAULT_SINGLE_PARTITION,
        field_set_type=fieldset_cls,
    ))
    lintreq_cls.__module__ = __name__


    @rule
    async def run_autolint(
            request: lintreq_cls.Batch,
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
                # argv=("/opt/homebrew/bin/markdownlint", *sources.files),
                # we can use sources.files to have all the files.
                input_digest=input_digest,
                description=f"Run {conf.name}",
                level=LogLevel.INFO,
                env=conf.extra_env
                # env={"PATH": "/opt/homebrew/bin/"}
            ),
        )
        return LintResult.create(request, process_result)

    return [
        *collect_rules(dict(locals())),
        *lintreq_cls.rules()
    ]


# _rules = build(_shellcheck)
_rules = build(_markdownlint)


def rules():
    return _rules
