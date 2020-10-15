# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import dataclasses
import json
import textwrap
from dataclasses import dataclass
from typing import Any, Dict, Generic, Optional, Sequence, Type, cast, get_type_hints

from pants.core.util_rules.pants_bin import PantsBin
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.rules import collect_rules, goal_rule
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
from pants.engine.unions import UnionMembership
from pants.util.objects import get_docstring, get_docstring_summary, pretty_print_type_hint


class TargetTypesSubsystem(LineOriented, GoalSubsystem):
    """List all registered target types."""

    name = "target-types"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--details",
            type=str,
            metavar="<target_type>",
            help="List all of the target type's registered fields.",
        )
        register(
            "--all",
            type=bool,
            default=False,
            help="List all target types with their full descriptions and fields as JSON.",
        )

    @property
    def details(self) -> Optional[str]:
        return cast(Optional[str], self.options.details)

    @property
    def all(self) -> bool:
        return cast(bool, self.options.all)


class TargetTypes(Goal):
    subsystem_cls = TargetTypesSubsystem


@dataclass(frozen=True)
class AbbreviatedTargetInfo:
    alias: str
    description: Optional[str]

    @classmethod
    def create(cls, target_type: Type[Target]) -> "AbbreviatedTargetInfo":
        return cls(alias=target_type.alias, description=get_docstring_summary(target_type))

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
        description = get_docstring(
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
            default=(
                repr(field.default) if (not field.required and field.default is not None) else None
            ),
        )

    def format_for_cli(self, console: Console) -> str:
        field_alias = console.magenta(f"{self.alias}")
        indent = "    "
        required_or_default = "required" if self.required else f"default: {self.default}"
        type_info = console.cyan(f"{indent}type: {self.type_hint}, {required_or_default}")
        lines = [field_alias, type_info]
        if self.description:
            lines.extend(f"{indent}{line}" for line in textwrap.wrap(self.description or "", 80))
        return "\n".join(f"{indent}{line}" for line in lines)

    def as_dict(self) -> Dict[str, Any]:
        d = dataclasses.asdict(self)
        del d["alias"]
        return d


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
                if not field.alias.startswith("_") and field.deprecated_removal_version is None
            ],
        )

    def format_for_cli(self, console: Console) -> str:
        output = [console.green(f"{self.alias}\n{'-' * len(self.alias)}\n")]
        if self.description:
            output.append(f"{self.description}\n")
        output.extend(
            [
                "Valid fields:\n",
                *sorted(f"{field.format_for_cli(console)}\n" for field in self.fields),
            ]
        )
        return "\n".join(output).rstrip()

    def as_dict(self) -> Dict[str, Any]:
        return {
            "description": self.description,
            "fields": {f.alias: f.as_dict() for f in self.fields},
        }


@goal_rule
def list_target_types(
    registered_target_types: RegisteredTargetTypes,
    union_membership: UnionMembership,
    target_types_subsystem: TargetTypesSubsystem,
    console: Console,
    pants_bin: PantsBin,
) -> TargetTypes:
    with target_types_subsystem.line_oriented(console) as print_stdout:
        if target_types_subsystem.all:
            all_target_types = {
                alias: VerboseTargetInfo.create(
                    target_type, union_membership=union_membership
                ).as_dict()
                for alias, target_type in registered_target_types.aliases_to_types.items()
                if not alias.startswith("_") and target_type.deprecated_removal_version is None
            }
            print_stdout(json.dumps(all_target_types, sort_keys=True, indent=4))
        elif target_types_subsystem.details:
            alias = target_types_subsystem.details
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
                if (
                    not target_type.alias.startswith("_")
                    and target_type.deprecated_removal_version is None
                )
            ]
            longest_target_alias = max(
                len(target_type.alias) for target_type in registered_target_types.types
            )
            lines = [
                f"\n{title}\n",
                textwrap.fill(
                    f"Use `{pants_bin.render_command('target-types', '--details=$target_type')}` "
                    "to get detailed information for a particular target type.",
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
    return collect_rules()
