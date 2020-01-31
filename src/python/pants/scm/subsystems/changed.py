# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from enum import Enum
from typing import Any

from pants.subsystem.subsystem import Subsystem


class IncludeDependeesOption(Enum):
  NONE = "none"
  DIRECT = "direct"
  TRANSITIVE = "transitive"


@dataclass(frozen=True)
class ChangedRequest:
  """Parameters required to compute a changed file/target set."""
  changes_since: Any
  diffspec: Any
  include_dependees: IncludeDependeesOption
  fast: Any

  @classmethod
  def from_options(cls, options) -> "ChangedRequest":
    """Given an `Options` object, produce a `ChangedRequest`."""
    return cls(options.changes_since,
               options.diffspec,
               options.include_dependees,
               options.fast)

  def is_actionable(self):
    return bool(self.changes_since or self.diffspec)


class Changed(Subsystem):
  """A subsystem for global `changed` functionality.

  This supports the "legacy" `changed`, `test-changed` and `compile-changed` goals as well as the
  v2 engine style `--changed-*` argument target root replacements which can apply to any goal (e.g.
  `./pants --changed-parent=HEAD~3 list` replaces `./pants --changed-parent=HEAD~3 changed`).
  """
  options_scope = 'changed'

  @classmethod
  def register_options(cls, register):
    register('--changes-since', '--parent', '--since',
             help='Calculate changes since this tree-ish/scm ref (defaults to current HEAD/tip).')
    register('--diffspec',
             help='Calculate changes contained within given scm spec (commit range/sha/ref/etc).')
    register('--include-dependees', type=IncludeDependeesOption, default=IncludeDependeesOption.NONE,
             help='Include direct or transitive dependees of changed targets.')
    register('--fast', type=bool,
             help='Stop searching for owners once a source is mapped to at least one owning target.')
