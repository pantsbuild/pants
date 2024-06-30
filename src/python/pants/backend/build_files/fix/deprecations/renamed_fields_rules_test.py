# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.build_files.fix.deprecations.renamed_fields_rules import (
    RenamedFieldTypes,
    RenameFieldsInFileRequest,
    determine_renamed_field_types,
    fix_single,
)
from pants.engine.target import RegisteredTargetTypes, StringField, Target, TargetGenerator
from pants.engine.unions import UnionMembership
from pants.util.frozendict import FrozenDict


def test_determine_renamed_fields() -> None:
    class DeprecatedField(StringField):
        alias = "new_name"
        deprecated_alias = "old_name"
        deprecated_alias_removal_version = "99.9.0.dev0"

    class OkayField(StringField):
        alias = "okay"

    class Tgt(Target):
        alias = "tgt"
        core_fields = (DeprecatedField, OkayField)
        deprecated_alias = "deprecated_tgt"
        deprecated_alias_removal_version = "99.9.0.dev0"

    class TgtGenerator(TargetGenerator):
        alias = "generator"
        core_fields = ()
        moved_fields = (DeprecatedField, OkayField)

    registered_targets = RegisteredTargetTypes.create([Tgt, TgtGenerator])
    result = determine_renamed_field_types.rule.func(registered_targets, UnionMembership({}))  # type: ignore[attr-defined]
    deprecated_fields = FrozenDict({DeprecatedField.deprecated_alias: DeprecatedField.alias})
    assert result.target_field_renames == FrozenDict(
        {k: deprecated_fields for k in (TgtGenerator.alias, Tgt.alias, Tgt.deprecated_alias)}
    )


@pytest.mark.parametrize(
    "lines",
    (
        # Already valid.
        ["target(new_name='')"],
        ["target(new_name = 56 ) "],
        ["target(foo=1, new_name=2)"],
        ["target(", "new_name", "=3)"],
        # Unrelated lines.
        ["", "123", "target()", "name='new_name'"],
        ["unaffected(deprecated_name='not this target')"],
        ["target(nested=here(deprecated_name='too deep'))"],
    ),
)
def test_rename_deprecated_field_types_noops(lines: list[str]) -> None:
    content = "\n".join(lines).encode("utf-8")
    result = fix_single.rule.func(  # type: ignore[attr-defined]
        RenameFieldsInFileRequest("BUILD", content=content),
        RenamedFieldTypes.from_dict({"target": {"deprecated_name": "new_name"}}),
    )
    assert result.content == content


@pytest.mark.parametrize(
    "lines,expected",
    (
        (["tgt1(deprecated_name='')"], ["tgt1(new_name='')"]),
        (["tgt1 ( deprecated_name = ' ', ", ")"], ["tgt1 ( new_name = ' ', ", ")"]),
        (["tgt1(deprecated_name='')  # comment"], ["tgt1(new_name='')  # comment"]),
        (["tgt1(", "deprecated_name", "=", ")"], ["tgt1(", "new_name", "=", ")"]),
    ),
)
def test_rename_deprecated_field_types_rewrite(lines: list[str], expected: list[str]) -> None:
    result = fix_single.rule.func(  # type: ignore[attr-defined]
        RenameFieldsInFileRequest("BUILD", content="\n".join(lines).encode("utf-8")),
        RenamedFieldTypes.from_dict({"tgt1": {"deprecated_name": "new_name"}}),
    )
    assert result.content == "\n".join(expected).encode("utf-8")
