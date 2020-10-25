# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import difflib

from pants.engine.target import RegisteredTargetTypes
from pants.engine.unions import UnionMembership
from pants.help.help_info_extracter import HelpInfoExtracter
from pants.help.maybe_color import MaybeColor
from pants.option.errors import UnknownFlagsError
from pants.option.options import Options
from pants.option.scope import GLOBAL_SCOPE


class FlagErrorHelpPrinter(MaybeColor):
    """Prints help related to erroneous command-line flag specification to the console."""

    def __init__(self, options: Options):
        super().__init__(options.for_global_scope().colors)
        self._bin_name = options.for_global_scope().pants_bin_name
        self._all_help_info = HelpInfoExtracter.get_all_help_info(
            options,
            # We only care about the options-related help info, so we pass in
            # dummy values for the other arguments.
            UnionMembership({}),
            lambda x: tuple(),
            RegisteredTargetTypes({}),
        )

    def handle_unknown_flags(self, err: UnknownFlagsError):
        global_flags = self._all_help_info.scope_to_help_info[GLOBAL_SCOPE].collect_unscoped_flags()
        oshi_for_scope = self._all_help_info.scope_to_help_info.get(err.arg_scope)
        possibilities = set(oshi_for_scope.collect_unscoped_flags()) if oshi_for_scope else set()

        if err.arg_scope == GLOBAL_SCOPE:
            # We allow all scoped flags for any scope in the global scope position on
            # the cmd line (that is, to the left of any goals).
            for oshi in self._all_help_info.scope_to_help_info.values():
                possibilities.update(oshi.collect_scoped_flags())

        for flag in err.flags:
            print(f"Unknown flag {self.maybe_red(flag)} on {err.arg_scope or 'global'} scope")
            did_you_mean = difflib.get_close_matches(flag, possibilities)
            if err.arg_scope != GLOBAL_SCOPE and flag in global_flags:
                # It's a common error to use a global flag in a goal scope, so we special-case it.
                print(
                    f"Did you mean to use the global {self.maybe_cyan(flag)}? Global options must "
                    f"come before any goals, or after any file/target arguments."
                )
            elif did_you_mean:
                print(f"Did you mean {', '.join(self.maybe_cyan(g) for g in did_you_mean)}?")

            help_cmd = (
                f"{self._bin_name} help"
                f"{'' if err.arg_scope == GLOBAL_SCOPE else (' ' + err.arg_scope)}"
            )
            print(f"Use `{self.maybe_green(help_cmd)}` to get help.")
