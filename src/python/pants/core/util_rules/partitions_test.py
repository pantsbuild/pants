# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Any

import pytest

from pants.build_graph.address import Address
from pants.core.goals.fix import Partitions
from pants.core.util_rules.partitions import (
    Partition,
    PartitionerType,
    _PartitionFieldSetsRequestBase,
)
from pants.engine.rules import QueryRule
from pants.engine.target import FieldSet, MultipleSourcesField, SingleSourceField
from pants.option.option_types import SkipOption
from pants.option.subsystem import Subsystem
from pants.testutil.rule_runner import RuleRunner


class KitchenSource(SingleSourceField):
    pass


@dataclass(frozen=True)
class KitchenSingleUtensilFieldSet(FieldSet):
    required_fields = (KitchenSource,)

    utensil: SingleSourceField


@dataclass(frozen=True)
class KitchenMultipleUtensilsFieldSet(FieldSet):
    required_fields = (KitchenSource,)

    utensils: MultipleSourcesField


class KitchenSubsystem(Subsystem):
    options_scope = "kitchen"
    help = "a cookbook might help"
    name = "The Kitchen"
    skip = SkipOption("cook")


@pytest.mark.parametrize(
    "kitchen_field_set_type, field_sets",
    [
        (
            KitchenSingleUtensilFieldSet,
            (
                KitchenSingleUtensilFieldSet(
                    Address("//:bowl"), SingleSourceField("bowl.utensil", Address(""))
                ),
                KitchenSingleUtensilFieldSet(
                    Address("//:knife"), SingleSourceField("knife.utensil", Address(""))
                ),
            ),
        ),
        (
            KitchenMultipleUtensilsFieldSet,
            (
                KitchenMultipleUtensilsFieldSet(
                    Address("//:utensils"),
                    MultipleSourcesField(["*.utensil"], Address("")),
                ),
            ),
        ),
    ],
)
def test_default_single_partition_partitioner(kitchen_field_set_type, field_sets) -> None:
    class CookRequest:
        class PartitionRequest(_PartitionFieldSetsRequestBase[Any]):
            pass

        tool_subsystem = KitchenSubsystem
        field_set_type = kitchen_field_set_type

    rules = [
        *PartitionerType.DEFAULT_SINGLE_PARTITION.default_rules(CookRequest, by_file=True),
        QueryRule(Partitions, [CookRequest.PartitionRequest]),
    ]
    rule_runner = RuleRunner(rules=rules)
    rule_runner.write_files({"BUILD": "", "knife.utensil": "", "bowl.utensil": ""})
    partitions = rule_runner.request(Partitions, [CookRequest.PartitionRequest(field_sets)])
    assert partitions == Partitions(
        [
            Partition(
                (
                    "bowl.utensil",
                    "knife.utensil",
                ),
                None,
            )
        ]
    )

    rule_runner.set_options(["--kitchen-skip"])
    partitions = rule_runner.request(Partitions, [CookRequest.PartitionRequest(field_sets)])
    assert partitions == Partitions([])


@pytest.mark.parametrize(
    "kitchen_field_set_type, field_sets",
    [
        (
            KitchenSingleUtensilFieldSet,
            (
                KitchenSingleUtensilFieldSet(
                    Address("//:bowl"), SingleSourceField("bowl.utensil", Address(""))
                ),
                KitchenSingleUtensilFieldSet(
                    Address("//:knife"), SingleSourceField("knife.utensil", Address(""))
                ),
            ),
        ),
        (
            KitchenMultipleUtensilsFieldSet,
            (
                KitchenMultipleUtensilsFieldSet(
                    Address("//:utensils"),
                    MultipleSourcesField(["*.utensil"], Address("")),
                ),
            ),
        ),
    ],
)
def test_default_one_partition_per_input_partitioner(kitchen_field_set_type, field_sets) -> None:
    class CookRequest:
        class PartitionRequest(_PartitionFieldSetsRequestBase[Any]):
            pass

        tool_subsystem = KitchenSubsystem
        field_set_type = kitchen_field_set_type

    rules = [
        *PartitionerType.DEFAULT_ONE_PARTITION_PER_INPUT.default_rules(CookRequest, by_file=True),
        QueryRule(Partitions, [CookRequest.PartitionRequest]),
    ]
    rule_runner = RuleRunner(rules=rules)
    rule_runner.write_files({"BUILD": "", "knife.utensil": "", "bowl.utensil": ""})
    partitions = rule_runner.request(Partitions, [CookRequest.PartitionRequest(field_sets)])
    assert partitions == Partitions(
        [
            Partition(("bowl.utensil",), None),
            Partition(("knife.utensil",), None),
        ]
    )

    rule_runner.set_options(["--kitchen-skip"])
    partitions = rule_runner.request(Partitions, [CookRequest.PartitionRequest(field_sets)])
    assert partitions == Partitions([])
