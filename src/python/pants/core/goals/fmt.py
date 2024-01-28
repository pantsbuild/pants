# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from typing import Iterable

from pants.base.specs import Specs
from pants.core.goals._fix import AbstractFixRequest, FixFilesRequest, FixResult, FixTargetsRequest
from pants.core.goals._fix import Partitions as Partitions  # re-export
from pants.core.goals._fix import _do_fix
from pants.core.goals.multi_tool_goal_helper import BatchSizeOption, OnlyOption
from pants.engine.console import Console
from pants.engine.fs import Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.rules import Get, collect_rules, goal_rule
from pants.engine.unions import UnionMembership, UnionRule, union

logger = logging.getLogger(__name__)


FmtResult = FixResult


@union
class AbstractFmtRequest(AbstractFixRequest):
    is_formatter = True
    is_fixer = False

    @classmethod
    def _get_rules(cls) -> Iterable[UnionRule]:
        yield from super()._get_rules()
        yield UnionRule(AbstractFmtRequest, cls)
        yield UnionRule(AbstractFmtRequest.Batch, cls.Batch)


class FmtTargetsRequest(AbstractFmtRequest, FixTargetsRequest):
    @classmethod
    def _get_rules(cls) -> Iterable:
        yield from super()._get_rules()
        yield UnionRule(FmtTargetsRequest.PartitionRequest, cls.PartitionRequest)


class FmtFilesRequest(AbstractFmtRequest, FixFilesRequest):
    @classmethod
    def _get_rules(cls) -> Iterable:
        yield from super()._get_rules()
        yield UnionRule(FmtFilesRequest.PartitionRequest, cls.PartitionRequest)


class FmtSubsystem(GoalSubsystem):
    name = "fmt"
    help = "Autoformat source code."

    @classmethod
    def activated(cls, union_membership: UnionMembership) -> bool:
        return AbstractFmtRequest in union_membership

    only = OnlyOption("formatter", "isort", "shfmt")
    batch_size = BatchSizeOption(uppercase="Formatter", lowercase="formatter")


class Fmt(Goal):
    subsystem_cls = FmtSubsystem
    environment_behavior = Goal.EnvironmentBehavior.LOCAL_ONLY


@goal_rule
async def fmt(
    console: Console,
    specs: Specs,
    fmt_subsystem: FmtSubsystem,
    workspace: Workspace,
    union_membership: UnionMembership,
) -> Fmt:
    return await _do_fix(
        union_membership.get(AbstractFmtRequest),
        union_membership.get(FmtTargetsRequest.PartitionRequest),
        union_membership.get(FmtFilesRequest.PartitionRequest),
        Fmt,
        fmt_subsystem,
        specs,
        workspace,
        console,
        lambda request_type: Get(Partitions, FmtTargetsRequest.PartitionRequest, request_type),
        lambda request_type: Get(Partitions, FmtFilesRequest.PartitionRequest, request_type),
    )


def rules():
    return collect_rules()
