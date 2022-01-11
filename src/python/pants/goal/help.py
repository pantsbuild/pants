# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from abc import abstractmethod

from pants.base.exiter import ExitCode
from pants.base.specs import Specs
from pants.build_graph.build_configuration import BuildConfiguration
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
        all_help_info = HelpInfoExtracter.get_all_help_info(
            options,
            union_membership,
            graph_session.goal_consumed_subsystem_scopes,
            RegisteredTargetTypes.create(build_config.target_types),
            build_config,
        )
        global_options = options.for_global_scope()
        help_printer = HelpPrinter(
            bin_name=global_options.pants_bin_name,
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


class ThingHelpBuiltinGoal(HelpBuiltinGoalBase):
    name = "help"
    help = "Display usage message."
    aliases = (
        "-h",
        "--help",
    )

    def create_help_request(self, options: Options) -> HelpRequest:
        return ThingHelp(
            advanced=False,
            things=tuple(options.goals) + tuple(options.unknown_goals),
        )


class ThingHelpAdvancedBuiltinGoal(HelpBuiltinGoalBase):
    name = "help-advanced"
    help = "Help for advanced options."
    aliases = ("--help-advanced",)

    def create_help_request(self, options: Options) -> HelpRequest:
        return ThingHelp(
            advanced=True,
            things=tuple(options.goals) + tuple(options.unknown_goals),
        )


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
