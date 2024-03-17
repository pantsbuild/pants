# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
#
# The plugin is for tests purposes only.
#
from typing import Iterable, Optional, Tuple

from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.internals.native_engine import Address
from pants.engine.internals.target_adaptor import SourceBlock
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
from pants.util.frozendict import FrozenDict


class _SourceBlocksField(SequenceField[SourceBlock]):
    alias = "source_blocks"
    required = False
    expected_element_type = SourceBlock
    expected_type_description = "an iterable of SourceBlock"

    @classmethod
    def compute_value(
        cls, raw_value: Optional[Iterable[SourceBlock]], address: Address
    ) -> Optional[Tuple[SourceBlock, ...]]:
        computed_value = super().compute_value(raw_value, address)
        return computed_value


class _SourceBlocksSourceField(SingleSourceField):
    pass


class _SourceBlocksTarget(Target):
    alias = "source_blocks"
    core_fields = (_SourceBlocksField, _SourceBlocksSourceField)


class _SourceBlocksTargetGenerator(TargetGenerator):
    alias = "source_blocks_generator"
    generated_target_cls = _SourceBlocksTarget
    core_fields = (_SourceBlocksSourceField, _SourceBlocksField)
    copied_fields = (_SourceBlocksSourceField,)
    moved_fields = ()


class _GenerateSourceBlocksTargetRequest(GenerateTargetsRequest):
    generate_from = _SourceBlocksTargetGenerator


@rule
def _generate_source_blocks_target(request: _GenerateSourceBlocksTargetRequest) -> GeneratedTargets:
    source_blocks = request.generator[_SourceBlocksField].value
    source = request.generator[_SourceBlocksSourceField].value
    return GeneratedTargets(
        request.generator,
        [
            _SourceBlocksTarget(
                request.template,
                address=request.template_address.create_generated("target"),
                origin_source_blocks=FrozenDict(((source, source_blocks),)),
            )
        ],
    )


def target_types():
    return [_SourceBlocksTarget, _SourceBlocksTargetGenerator]


def rules():
    return [
        *collect_rules(),
        UnionRule(GenerateTargetsRequest, _GenerateSourceBlocksTargetRequest),
    ]


def build_file_aliases():
    return BuildFileAliases(objects={"source_block": SourceBlock})
