# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# TODO: This was written as a port of the original bash script, but since we have 
# more knowledge of the options and goals, we can make this more robust and accurate (after tests are written).

from __future__ import annotations

import logging
from enum import Enum

from pants.base.exiter import PANTS_SUCCEEDED_EXIT_CODE, ExitCode
from pants.base.specs import Specs
from pants.build_graph.build_configuration import BuildConfiguration
from pants.engine.unions import UnionMembership
from pants.goal.builtin_goal import BuiltinGoal
from pants.init.engine_initializer import GraphSession
from pants.option.option_types import EnumOption
from pants.option.options import Options
from pants.option.scope import GLOBAL_SCOPE
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


class Shell(Enum):
    BASH = "bash"
    ZSH = "zsh"


class CompletionBuiltinGoal(BuiltinGoal):
    name = "complete"
    help = softwrap(
        """
        Generates a completion script for the specified shell. The script is printed to stdout.

        For example, `pants complete --zsh > pants-completions.zsh` will generate a zsh
        completion script and write it to the file `my-pants-completions.zsh`. You can then
        source this file in your `.zshrc` file to enable completion for Pants.

        This command is also used by the completion scripts to generate the completion options using
        passthrough options. This usage is not intended for use by end users, but could be
        useful for building custom completion scripts.

        An example of this usage is in the bash completion script, where we use the following command:
        `pants complete -- ${COMP_WORDS[@]}`. This will generate the completion options for the
        current args, and then pass them to the bash completion script.
        """
    )

    shell = EnumOption(
        default=Shell.BASH,
        help="Which shell completion type should be printed to stdout.",
    )

    def run(
        self,
        *,
        build_config: BuildConfiguration,
        graph_session: GraphSession,
        options: Options,
        specs: Specs,
        union_membership: UnionMembership,
    ) -> ExitCode:
        """This function is called under two main circumstances.

        - By a user generating a completion script for their shell (e.g. `pants complete --zsh > pants-completions.zsh`)
        - By the shell completions script when the user attempts a tab completion (e.g. `pants <tab>`, `pants fmt lint che<tab>`, etc...)

        In the first case, we should generate a completion script for the specified shell and print it to stdout.
        In the second case, we should generate the completion options for the current command and print them to stdout.

        The trigger to determine which case we're in is the presence of the passthrough arguments. If there are passthrough
        arguments, then we're generating completion options. If there are no passthrough arguments, then we're generating
        a completion script.
        """
        if options._passthru:
            completion_options = self._generate_completion_options(options)
            print("\n".join(completion_options))
            return PANTS_SUCCEEDED_EXIT_CODE

        script = self._generate_completion_script(self.shell)
        print(script)
        return PANTS_SUCCEEDED_EXIT_CODE

    def _generate_completion_script(self, shell: Shell) -> str:
        """Generate a completion script for the specified shell.

        Implementation note: In practice, we're just going to read in
        and return the contents of the appropriate static completion script file.

        :param shell: The shell to generate a completion script for.
        :return: The completion script for the specified shell.
        """

    def _generate_completion_options(self, options: Options) -> list[str]:
        """Generate the completion options for the specified args.

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

        :param options: The options object for the current Pants run.
        :return: A list of completion options.
        """
        logger.debug(f"Completion passthrough options: {options._passthru}")
        current_word = options._passthru.pop()
        previous_goal = self._get_previous_goal(options._passthru)
        logger.debug(f"Current word is '{current_word}', and previous goal is '{previous_goal}'")

        all_goals = sorted([k for k, v in options.known_scope_to_info.items() if v.is_goal])

        # If there is no previous goal, then we're at the top-level Pants command, so show all goals or global options
        if not previous_goal:
            if current_word.startswith("-"):
                global_options = self._build_options_for_goal(options)
                candidate_options = [o for o in global_options if o.startswith(current_word)]
                return candidate_options

            candidate_goals = [g for g in all_goals if g.startswith(current_word)]
            return candidate_goals

        # If there is already a previous goal and current_word starts with a hyphen, then show scoped options for that goal
        if current_word.startswith("-"):
            scoped_options = self._build_options_for_goal(options, previous_goal)
            candidate_options = [o for o in scoped_options if o.startswith(current_word)]
            return candidate_options

        # If there is a previous goal and current_word does not start with a hyphen, then show remaining goals
        # excluding the goals that are already in the command
        candidate_goals = [
            g for g in all_goals if g.startswith(current_word) and g not in options._passthru
        ]
        return candidate_goals

    def _get_previous_goal(self, args: list[str]) -> str | None:
        """Get the most recent goal in the command arguments, so options can be correctly applied.

        This function will ignore hyphenated options when looking for the goal. The args list
        should never be empty, as we should always have at least the `pants` command.

        # TODO: Handle targets

        :param args: The list of arguments to search for the previous goal.
        :return: The previous goal, or None if there is no previous goal.
        """
        return next((arg for arg in reversed(args) if arg.isalnum()), None)

    def _build_options_for_goal(self, options: Options, goal: str = "") -> list[str]:
        """Build a list of stringified options for the specified goal, prefixed by `--`.

        :param options: The options object for the current Pants run.
        :param goal: The goal to build options for. Defaults to "" for the global scope.
        :return: A list of options for the specified goal.
        """
        if goal == GLOBAL_SCOPE:
            global_options = sorted(options.for_global_scope().as_dict().keys())
            return [f"--{o}" for o in global_options]

        try:
            logger.error(f"Getting options for goal {goal}")
            scoped_options = sorted(options.for_scope(goal).as_dict().keys())
            return [f"--{o}" for o in scoped_options]
        except Exception:
            # options.for_scope will throw if the goal is unknown, so we'll just return an empty list
            # Since this is used for user-entered tab completion, it's not a warning or error
            logger.error(f"Unknown goal {goal}")
            return []
