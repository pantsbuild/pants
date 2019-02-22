# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
from builtins import object, set

from pants.subsystem.subsystem import Subsystem


logger = logging.getLogger(__name__)


class TargetFilter(Subsystem):
  """Filter targets matching configured criteria.

  :API: public
  """

  options_scope = 'target-filter'

  @classmethod
  def register_options(cls, register):
    super(TargetFilter, cls).register_options(register)

    register('--exclude-tags', type=list,
             default=[], fingerprint=True,
             help='Skip targets with given tag(s).')

  def apply(self, targets):
    exclude_tags = set(self.get_options().exclude_tags)
    return TargetFiltering(targets, exclude_tags).apply_tag_blacklist()


class TargetFiltering(object):
  """Apply filtering logic against targets."""

  def __init__(self, targets, exclude_tags):
    self.targets = targets
    self.exclude_tags = exclude_tags

  def apply_tag_blacklist(self):
    return [t for t in self.targets if not self.exclude_tags.intersection(t.tags)]
