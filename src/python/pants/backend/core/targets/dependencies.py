# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.base.payload import EmptyPayload
from pants.base.target import Target


class Dependencies(Target):
  """A set of dependencies that may be depended upon,
  as if depending upon the set of dependencies directly.
  """

  def __init__(self, *args, **kwargs):
    """
    :param string name: The name of this target, which combined with this
      build file defines the :doc:`target address <target_addresses>`.
    :param dependencies: Other targets that this target depends on.
    :type dependencies: list of target specs
    :param exclusives: An optional map of exclusives tags. See CheckExclusives
      for details.
    """
    super(Dependencies, self).__init__(payload=EmptyPayload(), *args, **kwargs)
