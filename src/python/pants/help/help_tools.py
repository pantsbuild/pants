# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from itertools import chain
from textwrap import wrap
from typing import Generator, Iterable, cast

from pants.help.help_info_extracter import AllHelpInfo, OptionScopeHelpInfo
from pants.help.maybe_color import MaybeColor
from pants.util.docutil import terminal_width


@dataclass(frozen=True)
class ToolHelpInfo:
    name: str
    description: str
    version: str
    url_template: str | None

    @classmethod
    def from_option_scope_help_info(cls, oshi: OptionScopeHelpInfo) -> ToolHelpInfo | None:
        version, url_template = cls._get_tool_info(oshi)
        if not version:
            return None
        return cls(
            name=oshi.scope,
            description=oshi.description,
            version=version,
            url_template=url_template,
        )

    @classmethod
    def iter(cls, all_help_info: AllHelpInfo) -> Generator[ToolHelpInfo, None, None]:
        for oshi in all_help_info.non_deprecated_option_scope_help_infos():
            tool_info = cls.from_option_scope_help_info(oshi)
            if tool_info:
                yield tool_info

    @staticmethod
    def print_all(tool_help_infos: Iterable[ToolHelpInfo], color: MaybeColor) -> None:
        this = tuple(tool_help_infos)
        longest_name = max(len(tool.name) for tool in this)
        width = terminal_width()

        for tool in this:
            tool.print(color, description_padding=longest_name + 2, width=width)

    def print(self, color: MaybeColor, description_padding: int, width: int) -> None:
        _wrap = partial(wrap, width=width)
        _max_padding = partial(
            min, int(width / 4)
        )  # Do not use more than 25% of the width on padding.

        def _indent(indent: int) -> str:
            return " " * cast(int, _max_padding(indent))

        lines = _wrap(
            f"{self.name.ljust(description_padding)}{self.description}",
            subsequent_indent=_indent(description_padding),
        )
        lines[0] = lines[0].replace(self.name, color.maybe_cyan(self.name), 1)
        version = _wrap(
            f"Version: {self.version}",
            initial_indent=_indent(description_padding),
            subsequent_indent=_indent(description_padding),
        )
        if not self.url_template:
            url_template = []
        else:
            url_template = _wrap(
                f"URL template: {self.url_template}",
                initial_indent=_indent(description_padding),
                subsequent_indent=_indent(description_padding),
            )
        print("\n".join(lines))
        print(color.maybe_magenta("\n".join([*version, *url_template, ""])))

    @classmethod
    def _get_tool_info(cls, oshi: OptionScopeHelpInfo) -> tuple[str | None, str | None]:
        return (
            cls._get_option_value(oshi, "version"),
            cls._get_option_value(oshi, "url_template"),
        )

    @staticmethod
    def _get_option_value(oshi: OptionScopeHelpInfo, config_key: str) -> str | None:
        for ohi in chain(oshi.basic, oshi.advanced):
            if ohi.config_key == config_key and ohi.typ is str:
                rank = ohi.value_history and ohi.value_history.final_value
                if rank:
                    info = f" ({rank.details})" if rank.details else ""
                    return f"{rank.value}{info}"
                return cast(str, ohi.default)
        return None
