# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, cast

from pants.goal.workspace import ScmWorkspace
from pants.scm.scm import Scm
from pants.subsystem.subsystem import Subsystem


class IncludeDependeesOption(Enum):
  NONE = "none"
  DIRECT = "direct"
  TRANSITIVE = "transitive"


@dataclass(frozen=True)
class ChangedRequest:
  """Parameters required to compute a changed file/target set."""
  changes_since: Optional[str]
  diffspec: Optional[str]
  include_dependees: IncludeDependeesOption
  fast: bool

  @classmethod
  def from_options(cls, options) -> "ChangedRequest":
    """Given an `Options` object, produce a `ChangedRequest`."""
    return cls(options.changes_since, options.diffspec, options.include_dependees, options.fast)

  def is_actionable(self) -> bool:
    return bool(self.changes_since or self.diffspec)

  def changed_files(self, *, scm: Scm) -> List[str]:
    """Determines the files changed according to SCM/workspace and options."""
    workspace = ScmWorkspace(scm)
    if self.diffspec:
      return cast(List[str], workspace.changes_in(self.diffspec))

    changes_since = self.changes_since or scm.current_rev_identifier
    return cast(List[str], workspace.touched_files(changes_since))


class Changed(Subsystem):
  """A subsystem for global `changed` functionality.

  This supports the `--changed-*` argument target root replacements, e.g.
  `./pants --changed-parent=HEAD~3 list`.
  """
  options_scope = 'changed'

  @classmethod
  def register_options(cls, register):
    register('--changes-since', '--parent', '--since', type=str, default=None,
             help='Calculate changes since this tree-ish/scm ref (defaults to current HEAD/tip).')
    register('--diffspec', type=str, default=None,
             help='Calculate changes contained within given scm spec (commit range/sha/ref/etc).')
    register('--include-dependees', type=IncludeDependeesOption, default=IncludeDependeesOption.NONE,
             help='Include direct or transitive dependees of changed targets.')
    register('--fast', type=bool, default=False,
             help='Stop searching for owners once a source is mapped to at least one owning target.')
