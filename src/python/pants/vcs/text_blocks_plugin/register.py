# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
#
# The plugin is for tests purposes only.
#
from typing import Iterable, Optional, Tuple

from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.internals.native_engine import Address
from pants.engine.internals.target_adaptor import TextBlock
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    GeneratedTargets,
    GenerateTargetsRequest,
    SequenceField,
    SingleSourceField,
    Target,
    TargetGenerator,
)
from pants.engine.unions import UnionRule


class _TextBlocksField(SequenceField[TextBlock]):
    alias = "text_blocks"
    required = False
    expected_element_type = TextBlock
    expected_type_description = "an iterable of TextBlock"

    @classmethod
    def compute_value(
        cls, raw_value: Optional[Iterable[TextBlock]], address: Address
    ) -> Optional[Tuple[TextBlock, ...]]:
        computed_value = super().compute_value(raw_value, address)
        return computed_value


class _TextBlocksSource(SingleSourceField):
    pass


class _TextBlocksTarget(Target):
    alias = "text_blocks"
    core_fields = (_TextBlocksField, _TextBlocksSource)


class _TextBlocksTargetGenerator(TargetGenerator):
    alias = "text_blocks_generator"
    generated_target_cls = _TextBlocksTarget
    core_fields = (_TextBlocksSource, _TextBlocksField)
    copied_fields = (_TextBlocksSource,)
    moved_fields = ()


class _GenerateTextBlocksTargetRequest(GenerateTargetsRequest):
    generate_from = _TextBlocksTargetGenerator


@rule
def _generate_text_blocks_target(request: _GenerateTextBlocksTargetRequest) -> GeneratedTargets:
    return GeneratedTargets(
        request.generator,
        [
            _TextBlocksTarget(
                request.template,
                address=request.template_address.create_generated("target"),
                origin_text_blocks=request.generator[_TextBlocksField].value,
            )
        ],
    )


def target_types():
    return [_TextBlocksTarget, _TextBlocksTargetGenerator]


def rules():
    return [
        *collect_rules(),
        UnionRule(GenerateTargetsRequest, _GenerateTextBlocksTargetRequest),
    ]


def build_file_aliases():
    return BuildFileAliases(objects={"text_block": TextBlock})
