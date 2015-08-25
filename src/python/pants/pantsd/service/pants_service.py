# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import threading
from abc import abstractmethod

from pants.util.meta import AbstractClass


class PantsService(threading.Thread, AbstractClass):
  """Pants daemon service base class."""

  class ServiceError(Exception): pass

  def __init__(self, kill_switch):
    """
    :param `threading.Event` kill_switch: A threading.Event to facilitate graceful shutdown of
                                          services. Subclasses should check if this is set using
                                          self.kill_switch.is_set() in their core runtime. If set,
                                          the service should teardown and gracefully exit. This
                                          should only ever be set by the service runner and is a
                                          fatal/one-time event for the service.
    """
    threading.Thread.__init__(self)
    self.name = self.__class__.__name__
    self.daemon = True
    self._kill_switch = kill_switch

  @property
  def kill_switch(self):
    return self._kill_switch

  @abstractmethod
  def run(self):
    """The main entry-point for the service called by the service runner."""
