# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging

from pants.subsystem.subsystem import Subsystem


logger = logging.getLogger(__name__)


class TargetFilter(Subsystem):
  """Filter out targets matching given options.

  :API: public
  """

  options_scope = 'target-filter'

  @classmethod
  def register_options(cls, register):
    super(TargetFilter, cls).register_options(register)

    register('--exclude-tags', type=list,
             default=[],
             help='Skip targets with given tag(s).')

  def apply(self, targets):
    exclude_tags = set(self.get_options().exclude_tags)
    return TargetFiltering.apply_tag_blacklist(exclude_tags, targets)


class TargetFiltering(object):
  """Apply filtering logic against targets."""

  @staticmethod
  def apply_tag_blacklist(exclude_tags, targets):
    return [t for t in targets if not exclude_tags.intersection(t.tags)]
