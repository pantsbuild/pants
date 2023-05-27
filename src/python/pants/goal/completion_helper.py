# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from typing import Iterable

from pants.base.exiter import PANTS_FAILED_EXIT_CODE, PANTS_SUCCEEDED_EXIT_CODE, ExitCode
from pants.base.specs import Specs
from pants.bsp import spec
from pants.build_graph.build_configuration import BuildConfiguration
from pants.engine.unions import UnionMembership
from pants.goal.builtin_goal import BuiltinGoal
from pants.init.engine_initializer import GraphSession
from pants.option.options import Options
from pants.option.options_test import global_scope
from pants.util.memo import memoized_property

logger = logging.getLogger(__name__)

class CompletionHelperBuiltinGoal(BuiltinGoal):
    name = "completion-helper"
    help = "A shell completion helper. Not for human use."

    def _get_previous_goal(self, args: list[str]) -> str | None:
        """
        Get the most recent goal in the command arguments, so options can be correctly applied.
        
        This function will ignore hyphenated options when looking for the goal. The args list
        should never be empty, as we should always have at least the `pants` command.

        # TODO: Handle targets
        """

        # If there is only one argument, we're at the top-level Pants command, so no previous goal.
        # TODO: Do we need this?
        if len(args) < 2:
            return None

        # If there is a goal in the list of arguments, reverse the args and return the first 
        # non-hyphenated arg (which should be a goal).
        for arg in reversed(args[1:]):
            if not arg.startswith("-"):
                return arg

        return None
        
    

    def run(
        self,
        build_config: BuildConfiguration,
        graph_session: GraphSession,
        options: Options,
        specs: Specs,
        union_membership: UnionMembership,
    ) -> ExitCode:
        """
        This function is called by the shell completions when the user types `pants <tab>`.
        
        We're guaranteed to have at least two arguments (`["pants", ""]`). If there are only two arguments,
        then we're at the top-level Pants command, and we should show all goals. 
        - `pants <tab>` -> `... fmt fix lint list repl run test ...`
        
        If we're at the top-level and the user has typed a hyphen, then we should show global options.
        - `pants -<tab>` -> `... --pants-config-files --pants-distdir --pants-ignore ...`

        As we add goals, we should show the remaining goals that are available.
        - `pants fmt fix lint <tab>` -> `... list repl run test ...`

        If there is a goal in the list of arguments and the user has typed a hyphen, then we should 
        show the available scoped options for the previous goal.
        - `pants fmt -<tab>` -> `... --only ...`

        # TODO: Handle targets
        """
        current_word = options._passthru.pop()
        previous_goal = self._get_previous_goal(options._passthru)
        # logger.error(f"{options._passthru} - {current_word} - {previous_goal} ")

        global_options = sorted(options.for_global_scope().as_dict().keys())
        global_options = [f"--{o}" for o in global_options]

        all_goals = [k for k,v in options.known_scope_to_info.items() if v.is_goal]
        all_goals = sorted(all_goals)

        # If there is no previous goal, then we're at the top-level Pants command, so show all goals or global options
        if not previous_goal:
            if current_word.startswith("-"):
                candidate_options = [o for o in global_options if o.startswith(current_word)]
                print(" ".join(candidate_options))
            else:
                candidate_goals = [g for g in all_goals if g.startswith(current_word)]
                print(" ".join(candidate_goals))
            return PANTS_SUCCEEDED_EXIT_CODE

        # If there is a previous goal and current_word starts with a hyphen, then show scoped options
        if current_word.startswith("-"):
            scoped_options = sorted(options.for_scope(previous_goal).as_dict().keys())
            scoped_options = [f"--{o}" for o in scoped_options]
            candidate_options = [o for o in scoped_options if o.startswith(current_word)]
            print(" ".join(candidate_options))
            return PANTS_SUCCEEDED_EXIT_CODE

        # If there is a previous goal and current_word does not start with a hyphen, then show remaining goals
        # excluding the goals that are already in the command
        candidate_goals = [g for g in all_goals if g.startswith(current_word) and g not in options._passthru]
        print(" ".join(candidate_goals))
        return PANTS_SUCCEEDED_EXIT_CODE
    
