# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Type, get_type_hints

from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.rules import UnionMembership, goal_rule
from pants.engine.target import AsyncField, Field, PrimitiveField, RegisteredTargetTypes, Target
from pants.util.objects import get_docstring, get_docstring_summary, pretty_print_type_hint


class TargetTypesOptions(LineOriented, GoalSubsystem):
    """List all the registered target types, including custom plugin types."""

    # TODO: drop the `2` once we settle on this name. Consider a more general goal like
    #  `symbols --type=targets`.
    name = "target-types2"

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


def abbreviated_target_information(
    target_type: Type[Target], console: Console, *, longest_target_alias: int
) -> str:
    """Return a single line description of the target type."""
    formatted_alias = console.cyan(f"{target_type.alias:>{longest_target_alias + 1}}:")
    description = get_docstring_summary(target_type) or "<no description>"
    return f"{formatted_alias} {description}"


def verbose_target_information(
    target_type: Type[Target], console: Console, union_membership: UnionMembership
) -> str:
    """Return a multiline description of the target type and all of its fields."""
    target_type_description = get_docstring(target_type)
    if target_type_description:
        target_type_description = console.blue(target_type_description)

    fields = target_type.class_field_types(union_membership=union_membership)
    longest_field_name = max(len(field.alias) for field in fields)

    async_field_docstring = get_docstring(AsyncField, flatten=True)
    primitive_field_docstring = get_docstring(PrimitiveField, flatten=True)

    # TODO: consider hard wrapping fields. It's confusing to read when fields soft wrap.
    def format_field(field: Type[Field]) -> str:
        field_alias_text = f"  {field.alias}"
        field_alias = console.cyan(f"{field_alias_text:<{longest_field_name + 2}}")
        # NB: It is very common (and encouraged) to subclass Fields to give custom behavior, e.g.
        # `PythonSources` subclassing `Sources`. Here, we set `fallback_to_parents=True` so that we
        # can still generate meaningful documentation for all these custom fields without requiring
        # the Field author to rewrite the docstring.
        #
        # However, if the original `Field` author did not define docstring, then this means we
        # would typically fall back to the docstring for `AsyncField` and `PrimitiveField`, which
        # is a grandparent for every field. This is a quirk of this heuristic and it's not
        # intentional. So, we hackily filter out the docstring for both those abstract classes.
        description = get_docstring(field, flatten=True, fallback_to_parents=True) or ""
        if description in (async_field_docstring, primitive_field_docstring):
            description = ""
        if issubclass(field, PrimitiveField):
            raw_value_type = get_type_hints(field.compute_value)["raw_value"]
        elif issubclass(field, AsyncField):
            raw_value_type = get_type_hints(field.sanitize_raw_value)["raw_value"]
        else:
            raw_value_type = get_type_hints(field.__init__)["raw_value"]
        type_info = console.green(
            f"(type: {pretty_print_type_hint(raw_value_type)}, default: {field.default})"
        )
        type_info_prefix = " " if description else ""
        return f"{field_alias}  {description}{type_info_prefix}{type_info}"

    output = [target_type_description, "\n"] if target_type_description else []
    output.extend(
        [
            console.blue(f"{target_type.alias}("),
            *sorted(format_field(field) for field in fields),
            console.blue(")"),
        ]
    )
    return "\n".join(output)


# TODO: allow exporting the information as JSON. This will enable us to use this goal to generate
#  documentation for the new website.
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
            print_stdout(
                "Use `./pants target-types2 --details=$target_type` to get detailed information "
                "for a particular target type.\n"
            )
            longest_target_alias = max(
                len(target_type.alias) for target_type in registered_target_types.types
            )
            for target_type in registered_target_types.types:
                description = abbreviated_target_information(
                    target_type, console, longest_target_alias=longest_target_alias
                )
                print_stdout(description)
    return TargetTypes(exit_code=0)


def rules():
    return [list_target_types]
