# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
from typing import Optional

from colors import black, blue, cyan, green, magenta, red, white
from packaging.version import Version

from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.internals.options_parsing import _Options
from pants.engine.rules import goal_rule
from pants.option.global_options import GlobalOptions
from pants.option.options import Options
from pants.option.options_fingerprinter import CoercingOptionEncoder
from pants.option.ranked_value import Rank
from pants.option.scope import GLOBAL_SCOPE
from pants.version import PANTS_SEMVER


class ExplainOptionsOptions(LineOriented, GoalSubsystem):
    """Display meta-information about options.

    This "meta-information" includes what values options have, and what values they *used* to have
    before they were overridden by a higher-rank value (eg, a HARDCODED value overridden by a CONFIG
    value and then a cli FLAG value).
    """

    name = "options"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register("--scope", help="Only show options in this scope. Use GLOBAL for global scope.")
        register("--name", help="Only show options with this name.")
        register(
            "--rank", type=Rank, help="Only show options with at least this importance.",
        )
        register(
            "--show-history",
            type=bool,
            help="Show the previous values options had before being overridden.",
        )
        register("--only-overridden", type=bool, help="Only show values that overrode defaults.")
        register(
            "--skip-inherited",
            type=bool,
            default=True,
            help="Do not show inherited options, unless their values differ from their parents.",
        )
        register(
            "--output-format",
            choices=["text", "json"],
            default="text",
            help="Specify the format options will be printed.",
        )


class ExplainOptions(Goal):
    subsystem_cls = ExplainOptionsOptions


class OptionsExplainer:
    def __init__(
        self,
        options: Options,
        scope: Optional[str],
        name: Optional[str],
        rank: Optional[Rank],
        show_history: bool,
        only_overridden: bool,
        skip_inherited: bool,
        output_format: str,
        colors: bool,
    ):
        self._options = options
        self._scope = scope
        self._name = name
        self._rank = rank
        self._show_history = show_history
        self._only_overridden = only_overridden
        self._skip_inherited = skip_inherited
        self._output_format = output_format
        self._colors = colors

    def _scope_filter(self, scope):
        return (
            not self._scope
            or scope.startswith(self._scope)
            or (self._scope == "GLOBAL" and scope == GLOBAL_SCOPE)
        )

    def _option_filter(self, option):
        if not self._name:
            return True
        return option == self._name.replace("-", "_")

    def _rank_filter(self, rank):
        if not self._rank:
            return True
        return rank >= self._rank

    def _rank_color(self, rank):
        if not self._colors:
            return lambda x: x
        if rank == Rank.NONE:
            return white
        if rank == Rank.HARDCODED:
            return white
        if rank == Rank.ENVIRONMENT:
            return red
        if rank == Rank.CONFIG:
            return blue
        if rank == Rank.FLAG:
            return magenta
        return black

    def _format_scope(self, scope, option, no_color=False):
        if no_color:
            return "{scope}{option}".format(
                scope="{}.".format(scope) if scope else "", option=option,
            )
        scope_color = cyan if self._colors else lambda x: x
        option_color = blue if self._colors else lambda x: x
        return "{scope}{option}".format(
            scope=scope_color("{}.".format(scope) if scope else ""), option=option_color(option),
        )

    def _format_record(self, record):
        simple_rank = record.rank.name
        if self.is_json():
            return record.value, simple_rank
        elif self.is_text():
            simple_value = str(record.value)
            value_color = green if self._colors else lambda x: x
            formatted_value = value_color(simple_value)
            rank_color = self._rank_color(record.rank)
            formatted_rank = "(from {rank}{details})".format(
                rank=simple_rank,
                details=rank_color(" {}".format(record.details)) if record.details else "",
            )
            return "{value} {rank}".format(value=formatted_value, rank=formatted_rank,)

    def _generate_history(self, history):
        for record in reversed(list(history)[:-1]):
            if record.rank > Rank.NONE:
                yield "  overrode {}".format(self._format_record(record))

    def _force_option_parsing(self):
        scopes = filter(self._scope_filter, list(self._options.known_scope_to_info.keys()))
        for scope in scopes:
            self._options.for_scope(scope)

    def _get_parent_scope_option(self, scope, name):
        if not scope:
            return None, None
        parent_scope = ""
        if "." in scope:
            parent_scope, _ = scope.rsplit(".", 1)
        options = self._options.for_scope(parent_scope)
        try:
            return parent_scope, options[name]
        except AttributeError:
            return None, None

    def is_json(self):
        return self._output_format == "json"

    def is_text(self):
        return self._output_format == "text"

    def generate(self):
        self._force_option_parsing()
        if self.is_json():
            output_map = {}
        for scope, scoped_options in sorted(self._options.tracker.option_history_by_scope.items()):
            if not self._scope_filter(scope):
                continue
            for option, history in sorted(scoped_options.items()):
                if not self._option_filter(option):
                    continue
                if not self._rank_filter(history.latest.rank):
                    continue
                if self._only_overridden and not history.was_overridden:
                    continue
                # Skip the option if it has already passed the deprecation period.
                if history.latest.deprecation_version and PANTS_SEMVER >= Version(
                    history.latest.deprecation_version
                ):
                    continue
                if self._skip_inherited:
                    parent_scope, parent_value = self._get_parent_scope_option(scope, option)
                    if parent_scope is not None and parent_value == history.latest.value:
                        continue
                if self.is_json():
                    value, rank_name = self._format_record(history.latest)
                    scope_key = self._format_scope(scope, option, True)
                    # We rely on the fact that option values are restricted to a set of types compatible with
                    # json. In particular, we expect dict, list, str, bool, int and float, and so do no
                    # processing here.
                    # TODO(John Sirois): The option parsing system currently lets options of unexpected types
                    # slide by, which can lead to un-overridable values and which would also blow up below in
                    # json encoding, fix options to restrict the allowed `type`s:
                    #   https://github.com/pantsbuild/pants/issues/4695
                    inner_map = dict(value=value, source=rank_name)
                    output_map[scope_key] = inner_map
                elif self.is_text():
                    yield "{} = {}".format(
                        self._format_scope(scope, option), self._format_record(history.latest)
                    )
                if self._show_history:
                    history_list = []
                    for line in self._generate_history(history):
                        if self.is_text():
                            yield line
                        elif self.is_json():
                            history_list.append(line.strip())
                    if self.is_json():
                        inner_map["history"] = history_list
        if self.is_json():
            yield json.dumps(output_map, indent=2, sort_keys=True, cls=CoercingOptionEncoder)


@goal_rule
def explain_options(
    explain_options_options: ExplainOptionsOptions,
    options_wrapper: _Options,
    global_options: GlobalOptions,
    console: Console,
) -> ExplainOptions:
    eoo = explain_options_options.values
    explainer = OptionsExplainer(
        options_wrapper.options,
        eoo.scope,
        eoo.name,
        eoo.rank,
        eoo.show_history,
        eoo.only_overridden,
        eoo.skip_inherited,
        eoo.output_format,
        global_options.options.colors,
    )
    with explain_options_options.line_oriented(console) as print_stdout:
        for content in explainer.generate():
            print_stdout(content)
    return ExplainOptions(0)


def rules():
    return [explain_options]
