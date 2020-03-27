# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

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

    def format_for_cli(self, *, console: Console, longest_target_alias: int) -> str:
        formatted_alias = console.cyan(f"{self.alias:>{longest_target_alias + 1}}:")
        description = self.description or "<no description>"
        return f"{formatted_alias} {description}"


@dataclass(frozen=True)
class FieldInfo:
    alias: str
    description: Optional[str]
    type_hint: str
    default: str

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
        return cls(
            alias=field.alias,
            description=description,
            type_hint=type_hint,
            default=str(field.default),
        )

    def format_for_cli(self, *, console: Console, longest_field_name: int) -> str:
        field_alias_text = f"  {self.alias}"
        field_alias = console.cyan(f"{field_alias_text:<{longest_field_name + 2}}")
        type_info = console.green(f"(type: {self.type_hint}, default: {self.default})")
        type_info_prefix = " " if self.description else ""
        return f"{field_alias}  {self.description or ''}{type_info_prefix}{type_info}"


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

    def format_for_cli(self, *, console: Console) -> str:
        output = [console.blue(self.description), "\n"] if self.description else []
        longest_field_name = max(len(field.alias) for field in self.fields)
        output.extend(
            [
                console.blue(f"{self.alias}("),
                *sorted(
                    field.format_for_cli(console=console, longest_field_name=longest_field_name)
                    for field in self.fields
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
            verbose_target_info = VerboseTargetInfo.create(
                target_type, union_membership=union_membership
            )
            print_stdout(verbose_target_info.format_for_cli(console=console))
        else:
            print_stdout(
                "Use `./pants target-types2 --details=$target_type` to get detailed information "
                "for a particular target type.\n"
            )
            longest_target_alias = max(
                len(target_type.alias) for target_type in registered_target_types.types
            )
            for target_type in registered_target_types.types:
                target_info = AbbreviatedTargetInfo.create(target_type)
                print_stdout(
                    target_info.format_for_cli(
                        console=console, longest_target_alias=longest_target_alias
                    )
                )
    return TargetTypes(exit_code=0)


def rules():
    return [list_target_types]
