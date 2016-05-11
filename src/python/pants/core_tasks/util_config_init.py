# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

from pants.task.task import Task
from pants.util.util_config import UtilConfig


logger = logging.getLogger(__name__)


class UtilConfigInit(Task):
  """List the repo's registered source roots."""

  @classmethod
  def register_options(cls, register):
    for configurable in UtilConfig.configurables.values():
      register(configurable.name, **configurable.init_parameters)

  def __init__(self, *vargs, **kwargs):
    super(UtilConfigInit, self).__init__(*vargs, **kwargs)
    for name, configurable in UtilConfig.configurables.items():
      option_value = self.get_options()[name]
      logger.debug('Initializing config option {} = {}.'.format(name, option_value))
      configurable.set_value(option_value)

  def execute(self):
    """We don't need to do anything in execute(); all we care about is that the options are copied.

    The options are copied in the init function rather than in execute() to ensure that it happens
    as soon as possible in the pants application lifecycle.
    """
