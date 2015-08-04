# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import threading
import time

from pants.util.meta import Singleton


class PantsService(threading.Thread, Singleton):
  """Pants daemon service base class."""

  def __init__(self, pantsd, options):
    threading.Thread.__init__(self)
    self.daemon = True

    self._name = self.__class__.__name__
    self._pantsd = pantsd
    self._options = options

  @property
  def name(self):
    return self._name

  @classmethod
  def _destroy_singleton(cls):
    """Destroy the singleton instance - necessary for thread restarts."""
    if hasattr(cls, 'instance'):
      del cls.instance

  def run(self):
    """The main entry-point for the service called by the service runner."""
    # We can't use @abstractmethod here due to metaclass collisions with Singleton.
    raise NotImplementedError()

  def _intentional_sleep(self):
    # TODO: remove this once services are bootstrapped.
    logging.getLogger().debug('sleeping 60s in {}'.format(self.__class__.__name__))
    time.sleep(60)
