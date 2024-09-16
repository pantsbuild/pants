# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""A Plugin development tool, to help check that naming conventions are followed in all loaded
backends.

Usage:

    $ ./pants --backend-packages=pants.backend.plugin_development.tools check-names --fix > apply-fixes-script.sh


Implemented checks:

  * Field classes should have a `Field` suffix on the class name. (`Mixin` and `Base` are also
    accepted, but not advertised.)
"""

from __future__ import annotations

import platform
from dataclasses import dataclass, field
from typing import Iterator, Sequence, cast

from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.rules import collect_rules, goal_rule
from pants.engine.target import Field
from pants.option.global_options import GlobalOptions
from pants.source.source_root import AllSourceRoots
from pants.util.strutil import bullet_list

_SED_REGEXP_WORD_BOUNDARIES = {
    "Darwin": {
        "begin": "[[:<:]]",
        "end": "[[:>:]]",
    },
    "Linux": {
        "begin": r"\b",
        "end": r"\b",
    },
}


class CheckNamesSubsystem(GoalSubsystem):
    name = "check-names"
    help = "Check names of things, that they follow Pantsbuild naming standards."

    @classmethod
    def register_options(cls, register):
        super().register_options(register)

        system = platform.system()

        register(
            "--sed-begin-word-boundary",
            type=str,
            default=_SED_REGEXP_WORD_BOUNDARIES[system]["begin"],
            help="The appropriate reg exp to use for `sed` to detect beginning of word boundaries.",
        )

        register(
            "--sed-end-word-boundary",
            type=str,
            default=_SED_REGEXP_WORD_BOUNDARIES[system]["end"],
            help="The appropriate reg exp to use for `sed` to detect ending of word boundaries.",
        )

        register(
            "--fix",
            type=bool,
            help="Generates a 'apply fixes' script to stdout.",
        )

    @property
    def begin_word_regexp(self) -> str:
        return cast(str, self.options.sed_begin_word_boundary)

    @property
    def end_word_regexp(self) -> str:
        return cast(str, self.options.sed_end_word_boundary)

    @property
    def fix(self) -> bool:
        return cast(bool, self.options.fix)


class CheckNames(Goal):
    subsystem_cls = CheckNamesSubsystem


@dataclass
class Context:
    console: Console
    options: CheckNamesSubsystem
    output_script: bool = field(init=False)

    def __post_init__(self):
        self.output_script = self.options.fix
        if self.output_script:
            self.console.print_stderr("Generating 'apply fixes' script to stdout")
        else:
            self.console.print_stdout(
                "## Hint: use `--fix` to generate a script that can be executed to apply the "
                "suggested corrections."
            )

    def output(self, info: str, script: str | None = None) -> None:
        self.console.print_stderr(info)
        if not self.output_script:
            return

        if script is None:
            self.console.print_stdout(f"\n# {info}")
        else:
            self.console.print_stdout(script)


@goal_rule
async def check_names(
    console: Console,
    subsystem: CheckNamesSubsystem,
    asr: AllSourceRoots,
    global_options: GlobalOptions,
) -> CheckNames:
    backends = bullet_list(global_options.options.backend_packages)
    src_roots = " ".join(src_root.path or "." for src_root in asr)
    ctx = Context(console, subsystem)
    ctx.output(
        f"Checking code loaded for these backends:\n{backends}",
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -eufo pipefail",
                f"SOURCE_ROOTS={src_roots!r}\n",
            ]
        ),
    )

    exit_code = check_field_names(ctx)

    if exit_code == 0:
        sigil = console.sigil_succeeded()
        status = "All checks passed"
    else:
        sigil = console.sigil_failed()
        status = "Some checks failed"

    ctx.output(f"{sigil} {status}.")
    return CheckNames(exit_code)


def get_subclass_suffix_replacements(
    base_class: type,
    *replace_suffix: tuple[str, str],
    valid_suffixes: Sequence[str],
    default_suffix: str,
) -> Iterator[tuple[str, str, str]]:
    for cls in base_class.__subclasses__():
        for suffix in valid_suffixes:
            if cls.__name__.endswith(suffix):
                break
        else:
            strip = None
            for suffix, replacement in replace_suffix:
                if cls.__name__.endswith(suffix):
                    strip = -len(suffix)
                    break
            else:
                replacement = default_suffix
            yield cls.__name__, cls.__module__, cls.__name__[:strip] + replacement
        yield from get_subclass_suffix_replacements(
            cls, *replace_suffix, valid_suffixes=valid_suffixes, default_suffix=default_suffix
        )


def check_field_names(ctx: Context) -> int:
    ctx.output(
        "Checking field class names...",
        (
            "# Fix field class names\n"
            "cat <<EOF | sed -f - -i '' $(find $SOURCE_ROOTS -name \\*.py)"
        ),
    )
    exit_code = 0
    seen = set()
    for class_name, module, new_class_name in get_subclass_suffix_replacements(
        Field, ("Bases", "Base"), valid_suffixes=("Field", "Base", "Mixin"), default_suffix="Field"
    ):
        if class_name in seen:
            continue

        seen.add(class_name)
        class_name_regexp = (
            f"{ctx.options.begin_word_regexp}{class_name}{ctx.options.end_word_regexp}"
        )
        ctx.output(
            f"  * Rename: {module}.{class_name} => {new_class_name}",
            f"s/{class_name_regexp}/{new_class_name}/g",
        )
        exit_code = 1

    ctx.output("", "EOF\n")
    return exit_code


def rules():
    return collect_rules()
