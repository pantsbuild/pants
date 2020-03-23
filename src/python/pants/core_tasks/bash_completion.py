# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from collections import defaultdict

from pkg_resources import resource_string

from pants.base.exceptions import TaskError
from pants.base.generator import Generator
from pants.goal.goal import Goal
from pants.help.help_info_extracter import HelpInfoExtracter
from pants.option.scope import GLOBAL_SCOPE
from pants.task.console_task import ConsoleTask
from pants.task.task import TaskBase


class BashCompletion(ConsoleTask):
    """Generate a Bash shell script that teaches Bash how to autocomplete pants command lines."""

    _register_console_transitivity_option = False

    @staticmethod
    def _get_all_cmd_line_scopes():
        """Return all scopes that may be explicitly specified on the cmd line, in no particular
        order.

        Note that this includes only task scope, and not, say, subsystem scopes, as those aren't
        specifiable on the cmd line.
        """
        all_scopes = {GLOBAL_SCOPE}
        for goal in Goal.all():
            for task in goal.task_types():
                all_scopes.add(task.get_scope_info().scope)
        return all_scopes

    def get_autocomplete_options_by_scope(self):
        """Return all cmd-line options.

        These are of two types: scoped and unscoped.  Scoped options are explicitly scoped
        (e.g., --goal-task-foo-bar) and may appear anywhere on the cmd line. Unscoped options
        may only appear in the appropriate cmd line scope (e.g., ./pants goal.task --foo-bar).

        Technically, any scoped option can appear anywhere, but in practice, having so many
        autocomplete options is more confusing than useful. So, as a heuristic:
         1. In global scope we only autocomplete globally-registered options.
         2. In a goal scope we only autocomplete options registered by any task in that goal.
         3. In a task scope we only autocomplete options registered by that task.

        :return: A map of scope -> options to complete at that scope.
        """
        autocomplete_options_by_scope = defaultdict(set)

        def get_from_parser(parser):
            oschi = HelpInfoExtracter.get_option_scope_help_info_from_parser(parser)
            # We ignore advanced options, as they aren't intended to be used on the cmd line.
            for ohi in oschi.basic:
                autocomplete_options_by_scope[oschi.scope].update(ohi.unscoped_cmd_line_args)
                autocomplete_options_by_scope[oschi.scope].update(ohi.scoped_cmd_line_args)
                # Autocomplete to this option in the enclosing goal scope, but exclude options registered
                # on us, but not by us, e.g., recursive options (which are registered by
                # GlobalOptionsRegisterer).
                # We exclude those because they are already registered on the goal scope anyway
                # (via the recursion) and it would be confusing and superfluous to have autocompletion
                # to both --goal-recursive-opt and --goal-task-recursive-opt in goal scope.
                if issubclass(ohi.registering_class, TaskBase):
                    goal_scope = oschi.scope.partition(".")[0]
                    autocomplete_options_by_scope[goal_scope].update(ohi.scoped_cmd_line_args)

        self.context.options.walk_parsers(get_from_parser)
        return autocomplete_options_by_scope

    def console_output(self, targets):
        if targets:
            raise TaskError("This task does not accept any target addresses.")
        cmd_line_scopes = sorted(self._get_all_cmd_line_scopes())
        autocomplete_options_by_scope = self.get_autocomplete_options_by_scope()

        def bash_scope_key(sc):
            if sc == GLOBAL_SCOPE:
                return "__pants_global_options"
            else:
                return "__pants_options_for_{}".format(sc.replace("-", "_").replace(".", "_"))

        options_text_lines = []
        for scope in cmd_line_scopes:
            options_text_lines.append(
                "{}='{}'".format(
                    bash_scope_key(scope), " ".join(autocomplete_options_by_scope[scope])
                )
            )
        options_text = "\n".join(options_text_lines)

        generator = Generator(
            resource_string(
                __name__, os.path.join("templates", "bash_completion", "autocomplete.sh.mustache")
            ).decode(),
            scopes_text=" ".join(sorted(list(cmd_line_scopes))),
            options_text=options_text,
        )

        for line in generator.render().split("\n"):
            yield line
