# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""A Plugin development tool, to help check that naming conventions are followed in all loaded
backends.

Usage:

    $ ./pants --backend-packages=pants.backend.plugin_development check-names > renames
    $ find src/python -name \\*.py | xargs sed -i "" -f renames


Implemented checks:

  * Field classes should have a `Field` suffix on the class name. (`Mixin` and `Base` are also
    accepted, but not advertised.)
"""

from __future__ import annotations

from typing import Iterator

from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.rules import collect_rules, goal_rule
from pants.engine.target import Field


class CheckNamesSubsystem(GoalSubsystem):
    name = "check-names"
    help = "Check names of things, that they follow Pants naming standards."


class CheckNames(Goal):
    subsystem_cls = CheckNamesSubsystem


@goal_rule
async def check_names(console: Console, subsystem: CheckNamesSubsystem) -> CheckNames:
    console.print_stderr("Checking field class names...")
    exit_code = check_field_names(console)

    if exit_code == 0:
        sigil = console.sigil_succeeded()
        status = "All checks passed"
    else:
        sigil = console.sigil_failed()
        status = "Some checks failed"

    console.print_stderr(f"\n{sigil} {status}.")
    return CheckNames(exit_code)


def get_subclasses_name_does_not_end_with(
    base_class: type, *endswith: str
) -> Iterator[tuple[str, str]]:
    for cls in base_class.__subclasses__():
        for suffix in endswith:
            if cls.__name__.endswith(suffix):
                break
        else:
            yield cls.__name__, cls.__module__
        yield from get_subclasses_name_does_not_end_with(cls, *endswith)


def check_field_names(console: Console) -> int:
    exit_code = 0
    seen = set()
    for class_name, module in get_subclasses_name_does_not_end_with(
        Field, "Field", "Base", "Mixin"
    ):
        if class_name in seen:
            continue

        seen.add(class_name)
        console.print_stderr(f"Rename field class {module}.{class_name} => {class_name}Field")
        console.print_stdout(f"s/\\b{class_name}\\b/{class_name}Field/g")
        exit_code = 1

    return exit_code


def rules():
    return collect_rules()
