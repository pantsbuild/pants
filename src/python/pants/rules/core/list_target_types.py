# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Type

from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.rules import UnionMembership, goal_rule
from pants.engine.target import BoolField, Field, RegisteredTargetTypes, Target
from pants.util.objects import get_first_line_of_docstring


class TargetTypesOptions(LineOriented, GoalSubsystem):
    """List all the registered target types, including custom plugin types."""

    # TODO: consider renaming this to to `target-types` or even a more general goal like
    #  `symbols --type=targets`.
    name = "targets2"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--details",
            type=str,
            metavar="target_type",
            help="List all of the target type's registered fields.",
        )


class TargetTypes(Goal):
    subsystem_cls = TargetTypesOptions


def abbreviated_target_information(target_type: Type[Target], console: Console) -> str:
    """Return a single line description of the target type."""
    formatted_alias = console.cyan(f"{target_type.alias:>30}:")
    description = get_first_line_of_docstring(target_type) or "<no description>"
    return f"{formatted_alias} {description}"


def verbose_target_information(
    target_type: Type[Target], console: Console, union_membership: UnionMembership
) -> str:
    """Return a multiline description of the target type and all of its fields."""
    # TODO: show the full docstring for both the target type and each field. We first need to
    #  process them, e.g. removing all blank lines and possibly stripping type hints? See
    #  build_dictionary_info_extractor.py for inspiration.
    target_type_description = get_first_line_of_docstring(target_type)
    if target_type_description:
        target_type_description = console.blue(target_type_description)

    def format_field(field: Type[Field]) -> str:
        # TODO: possibly put type information in this output. We would extract it from the type
        #  hints, but it might be weird to handle Optional.
        field_alias_text = f"  {field.alias} = ...,"
        field_alias = console.cyan(f"{field_alias_text:<30}")
        description = get_first_line_of_docstring(field) or "<no description>"
        # TODO: should we elevate `default` so that every Field has it, whereas now only bool
        #  fields have it? V1 `targets` renders a default value, which is helpful.
        default = console.green(
            f"(default: {field.default})" if issubclass(field, BoolField) else ""
        )
        default_prefix = " " if default else ""
        return f"{field_alias}  {description}{default_prefix}{default}"

    output = [target_type_description, "\n"] if target_type_description else []
    output.extend(
        [
            console.blue(f"{target_type.alias}("),
            *sorted(
                format_field(field)
                for field in target_type.class_field_types(union_membership=union_membership)
            ),
            console.blue(")"),
        ]
    )
    return "\n".join(output)


@goal_rule
def list_target_types(
    registered_target_types: RegisteredTargetTypes,
    union_membership: UnionMembership,
    options: TargetTypesOptions,
    console: Console,
) -> TargetTypes:
    with options.line_oriented(console) as print_stdout:
        if options.values.details:
            alias = options.values.details
            target_type = registered_target_types.aliases_to_types.get(alias)
            if target_type is None:
                raise ValueError(
                    f"Unrecognized target type {repr(alias)}. All registered "
                    f"target types: {list(registered_target_types.aliases)}"
                )
            output = verbose_target_information(target_type, console, union_membership)
            print_stdout(output)
        else:
            for target_type in registered_target_types.types:
                description = abbreviated_target_information(target_type, console)
                print_stdout(description)
    return TargetTypes(exit_code=0)


def rules():
    return [list_target_types]
