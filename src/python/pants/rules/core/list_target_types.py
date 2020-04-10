# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import textwrap
from dataclasses import dataclass
from typing import Generic, Optional, Sequence, Type, get_type_hints

from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.rules import UnionMembership, goal_rule
from pants.engine.target import (
    AsyncField,
    BoolField,
    DictStringToStringField,
    DictStringToStringSequenceField,
    Field,
    FloatField,
    IntField,
    PrimitiveField,
    RegisteredTargetTypes,
    ScalarField,
    SequenceField,
    StringField,
    StringOrStringSequenceField,
    StringSequenceField,
    Target,
)
from pants.option.global_options import GlobalOptions
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
    v1_only: bool

    @classmethod
    def create(cls, target_type: Type[Target]) -> "AbbreviatedTargetInfo":
        return cls(
            alias=target_type.alias,
            description=get_docstring_summary(target_type),
            v1_only=target_type.v1_only,
        )

    def format_for_cli(self, console: Console, *, longest_target_alias: int) -> str:
        chars_before_description = longest_target_alias + 2
        alias = console.cyan(f"{self.alias}".ljust(chars_before_description))
        if not self.description:
            description = "<no description>"
        else:
            description_lines = textwrap.wrap(self.description, 80 - chars_before_description)
            if len(description_lines) > 1:
                description_lines = [
                    description_lines[0],
                    *(f"{' ' * chars_before_description}{line}" for line in description_lines[1:]),
                ]
            description = "\n".join(description_lines)
        return f"{alias}{description}\n"


@dataclass(frozen=True)
class FieldInfo:
    alias: str
    description: Optional[str]
    type_hint: str
    required: bool
    default: Optional[str]
    v1_only: bool

    @classmethod
    def create(cls, field: Type[Field]) -> "FieldInfo":
        # NB: It is very common (and encouraged) to subclass Fields to give custom behavior, e.g.
        # `PythonSources` subclassing `Sources`. Here, we set `fallback_to_ancestors=True` so that
        # we can still generate meaningful documentation for all these custom fields without
        # requiring the Field author to rewrite the docstring.
        #
        # However, if the original `Field` author did not define docstring, then this means we
        # would typically fall back to the docstring for `AsyncField`, `PrimitiveField`, or a
        # helper class like `StringField`. This is a quirk of this heuristic and it's not
        # intentional since these core `Field` types have documentation oriented to the custom
        # `Field` author and not the end user filling in fields in a BUILD file target.
        description = (
            get_docstring(
                field,
                flatten=True,
                fallback_to_ancestors=True,
                ignored_ancestors={
                    *Field.mro(),
                    AsyncField,
                    PrimitiveField,
                    BoolField,
                    DictStringToStringField,
                    DictStringToStringSequenceField,
                    FloatField,
                    Generic,  # type: ignore[arg-type]
                    IntField,
                    ScalarField,
                    SequenceField,
                    StringField,
                    StringOrStringSequenceField,
                    StringSequenceField,
                },
            )
            or ""
        )
        if issubclass(field, PrimitiveField):
            raw_value_type = get_type_hints(field.compute_value)["raw_value"]
        elif issubclass(field, AsyncField):
            raw_value_type = get_type_hints(field.sanitize_raw_value)["raw_value"]
        else:
            raw_value_type = get_type_hints(field.__init__)["raw_value"]
        type_hint = pretty_print_type_hint(raw_value_type)

        # Check if the field only allows for certain choices.
        if issubclass(field, StringField) and field.valid_choices is not None:
            valid_choices = sorted(
                field.valid_choices
                if isinstance(field.valid_choices, tuple)
                else (choice.value for choice in field.valid_choices)
            )
            type_hint = " | ".join([*(repr(c) for c in valid_choices), "None"])

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
            default=repr(field.default) if not field.required else None,
            v1_only=field.v1_only,
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

    def format_for_cli(self, console: Console, *, v1_disabled: bool) -> str:
        output = [console.green(f"{self.alias}\n{'-' * len(self.alias)}\n")]
        if self.description:
            output.append(f"{self.description}\n")
        output.extend(
            [
                "Valid fields:\n",
                *sorted(
                    f"{field.format_for_cli(console)}\n"
                    for field in self.fields
                    if not field.alias.startswith("_") and (not v1_disabled or not field.v1_only)
                ),
            ]
        )
        return "\n".join(output).rstrip()


@goal_rule
def list_target_types(
    registered_target_types: RegisteredTargetTypes,
    union_membership: UnionMembership,
    target_types_options: TargetTypesOptions,
    global_options: GlobalOptions,
    console: Console,
) -> TargetTypes:
    v1_disabled = not global_options.options.v1
    with target_types_options.line_oriented(console) as print_stdout:
        if target_types_options.values.details:
            alias = target_types_options.values.details
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
            print_stdout(verbose_target_info.format_for_cli(console, v1_disabled=v1_disabled))
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
                    if not target_info.alias.startswith("_")
                    and (not v1_disabled or not target_info.v1_only)
                ),
            ]
            print_stdout("\n".join(lines).rstrip())
    return TargetTypes(exit_code=0)


def rules():
    return [list_target_types]
