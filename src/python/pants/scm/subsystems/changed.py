# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from future.utils import text_type

from pants.option.global_options import IncludeDependees
from pants.subsystem.subsystem import Subsystem
from pants.util.objects import Exactly, datatype


class ChangedRequest(datatype([
    ('changes_since', Exactly(text_type, type(None))),
    ('diffspec', Exactly(text_type, type(None))),
    ('include_dependees', IncludeDependees),
    ('fast', bool)])):
  """Parameters required to compute a changed file/target set."""

  @classmethod
  def from_options(cls, options, include_dependees):
    """Given an `Options` object, produce a `ChangedRequest`."""
    return cls(options.changes_since,
               options.diffspec,
               include_dependees=include_dependees,
               fast=options.fast or False)

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
    register('--fast', type=bool,
             help='Stop searching for owners once a source is mapped to at least one owning target.')
