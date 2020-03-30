# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import textwrap
from dataclasses import dataclass
from typing import Optional, Sequence, Type, get_type_hints

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


@dataclass(frozen=True)
class AbbreviatedTargetInfo:
    alias: str
    description: Optional[str]

    @classmethod
    def create(cls, target_type: Type[Target]) -> "AbbreviatedTargetInfo":
        return cls(alias=target_type.alias, description=get_docstring_summary(target_type))

    def format_for_cli(self, console: Console, *, longest_target_alias: int) -> str:
        chars_before_description = longest_target_alias + 4
        alias = console.cyan(f"{self.alias}()".ljust(chars_before_description))
        if not self.description:
            description = "<no description>"
        else:
            description_lines = textwrap.wrap(self.description, 80 - chars_before_description)
            if len(description_lines) > 1:
                description_lines = [
                    description_lines[0],
                    *(
                        f"{' ' * (chars_before_description + 4)}{line}"
                        for line in description_lines[1:]
                    ),
                ]
            description = "\n".join(description_lines)
        return f"{alias}{description}"


@dataclass(frozen=True)
class FieldInfo:
    alias: str
    description: Optional[str]
    type_hint: str
    required: bool
    default: Optional[str]

    @classmethod
    def create(cls, field: Type[Field]) -> "FieldInfo":
        description = get_docstring(field, flatten=True)
        if issubclass(field, PrimitiveField):
            raw_value_type = get_type_hints(field.compute_value)["raw_value"]
        elif issubclass(field, AsyncField):
            raw_value_type = get_type_hints(field.sanitize_raw_value)["raw_value"]
        else:
            raw_value_type = get_type_hints(field.__init__)["raw_value"]
        type_hint = pretty_print_type_hint(raw_value_type)
        if field.required:
            # We hackily remove `None` as a valid option for the field when it's required. This
            # greatly simplifies Field definitions because it means that they don't need to
            # override the type hints for `PrimitiveField.compute_value()` and
            # `AsyncField.sanitize_raw_value()` to indicate that `None` is an invalid type.
            type_hint = type_hint.replace(" | None", "")
        return cls(
            alias=field.alias,
            description=description,
            type_hint=type_hint,
            required=field.required,
            default=str(field.default) if not field.required else None,
        )

    def format_for_cli(self, console: Console) -> str:
        field_alias = console.magenta(f"{self.alias}")
        indent = "    "
        required_or_default = "required" if self.required else f"default: {self.default}"
        type_info = console.cyan(f"{indent}type: {self.type_hint}, {required_or_default}")
        lines = [field_alias, type_info]
        if self.description:
            lines.extend(f"{indent}{line}" for line in textwrap.wrap(self.description, 80))
        return "\n".join(f"{indent}{line}" for line in lines)


@dataclass(frozen=True)
class VerboseTargetInfo:
    alias: str
    description: Optional[str]
    fields: Sequence[FieldInfo]

    @classmethod
    def create(
        cls, target_type: Type[Target], *, union_membership: UnionMembership
    ) -> "VerboseTargetInfo":
        return cls(
            alias=target_type.alias,
            description=get_docstring(target_type),
            fields=[
                FieldInfo.create(field)
                for field in target_type.class_field_types(union_membership=union_membership)
            ],
        )

    def format_for_cli(self, console: Console) -> str:
        output = [console.green(f"{self.alias}()\n{'-' * (len(self.alias) + 2)}\n")]
        if self.description:
            output.append(f"{self.description}\n")
        output.extend(
            [
                "Valid fields:\n",
                *sorted(f"{field.format_for_cli(console)}\n" for field in self.fields),
            ]
        )
        return "\n".join(output).rstrip()


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
            verbose_target_info = VerboseTargetInfo.create(
                target_type, union_membership=union_membership
            )
            print_stdout("")
            print_stdout(verbose_target_info.format_for_cli(console))
        else:
            title_text = "Target types"
            title = console.green(f"{title_text}\n{'-' * len(title_text)}")
            target_infos = [
                AbbreviatedTargetInfo.create(target_type)
                for target_type in registered_target_types.types
            ]
            longest_target_alias = max(
                len(target_type.alias) for target_type in registered_target_types.types
            )
            lines = [
                f"\n{title}\n",
                textwrap.fill(
                    "Use `./pants target-types2 --details=$target_type` to get detailed "
                    "information for a particular target type.",
                    80,
                ),
                "\n",
                *(
                    target_info.format_for_cli(console, longest_target_alias=longest_target_alias)
                    for target_info in target_infos
                ),
            ]
            print_stdout("\n".join(lines).rstrip())
    return TargetTypes(exit_code=0)


def rules():
    return [list_target_types]
