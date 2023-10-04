# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from abc import abstractmethod
from typing import ClassVar

from pants.base.exiter import ExitCode
from pants.base.specs import Specs
from pants.build_graph.build_configuration import BuildConfiguration
from pants.core.util_rules.environments import determine_bootstrap_environment
from pants.engine.internals.parser import BuildFileSymbolsInfo
from pants.engine.internals.selectors import Params
from pants.engine.target import RegisteredTargetTypes
from pants.engine.unions import UnionMembership
from pants.goal.builtin_goal import BuiltinGoal
from pants.help.help_info_extracter import HelpInfoExtracter
from pants.help.help_printer import HelpPrinter
from pants.init.engine_initializer import GraphSession
from pants.option.arg_splitter import (
    NO_GOAL_NAME,
    UNKNOWN_GOAL_NAME,
    AllHelp,
    HelpRequest,
    NoGoalHelp,
    ThingHelp,
    UnknownGoalHelp,
    VersionHelp,
)
from pants.option.options import Options


class HelpBuiltinGoalBase(BuiltinGoal):
    def run(
        self,
        build_config: BuildConfiguration,
        graph_session: GraphSession,
        options: Options,
        specs: Specs,
        union_membership: UnionMembership,
    ) -> ExitCode:
        env_name = determine_bootstrap_environment(graph_session.scheduler_session)
        build_symbols = graph_session.scheduler_session.product_request(
            BuildFileSymbolsInfo, [Params(env_name)]
        )[0]
        all_help_info = HelpInfoExtracter.get_all_help_info(
            options,
            union_membership,
            graph_session.goal_consumed_subsystem_scopes,
            RegisteredTargetTypes.create(build_config.target_types),
            build_symbols,
            build_config,
        )
        global_options = options.for_global_scope()
        help_printer = HelpPrinter(
            help_request=self.create_help_request(options),
            all_help_info=all_help_info,
            color=global_options.colors,
        )
        return help_printer.print_help()

    @abstractmethod
    def create_help_request(self, options: Options) -> HelpRequest:
        raise NotImplementedError


class AllHelpBuiltinGoal(HelpBuiltinGoalBase):
    name = "help-all"
    help = "Print a JSON object containing all help info."

    def create_help_request(self, options: Options) -> HelpRequest:
        return AllHelp()


class NoGoalHelpBuiltinGoal(HelpBuiltinGoalBase):
    name = NO_GOAL_NAME
    help = "(internal goal not presented on the CLI)"

    def create_help_request(self, options: Options) -> HelpRequest:
        return NoGoalHelp()


class ThingHelpBuiltinGoalBase(HelpBuiltinGoalBase):
    _advanced: ClassVar[bool]

    def create_help_request(self, options: Options) -> HelpRequest:
        # Include the `options.specs` for things to give help on, as args with any . : * or # in
        # them is deemed "likely a spec" by `pants.option.arg_splitter:ArgSplitter.likely_a_spec()`.
        # We want to support getting help on API types that may contain periods.
        return ThingHelp(
            advanced=self._advanced,
            things=tuple(options.goals) + tuple(options.unknown_goals),
            likely_specs=tuple(options.specs),
        )


class ThingHelpBuiltinGoal(ThingHelpBuiltinGoalBase):
    name = "help"
    help = "Display usage message."
    aliases = ("-h", "--help")
    _advanced = False


class ThingHelpAdvancedBuiltinGoal(ThingHelpBuiltinGoalBase):
    name = "help-advanced"
    help = "Help for advanced options."
    aliases = ("--help-advanced",)
    _advanced = True


class UnknownGoalHelpBuiltinGoal(HelpBuiltinGoalBase):
    name = UNKNOWN_GOAL_NAME
    help = "(internal goal not presented on the CLI)"

    def create_help_request(self, options: Options) -> HelpRequest:
        return UnknownGoalHelp(tuple(options.unknown_goals))


class VersionHelpBuiltinGoal(HelpBuiltinGoalBase):
    name = "version"
    help = "Display Pants version."
    aliases = ("-v", "-V", "--version")

    def create_help_request(self, options: Options) -> HelpRequest:
        return VersionHelp()
