# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractmethod

from pants.util.meta import AbstractClass


class PantsService(AbstractClass):
  """Pants daemon service base class."""

  class ServiceError(Exception): pass

  def __init__(self, kill_switch):
    """
    :param `threading.Event` kill_switch: A threading.Event to facilitate graceful shutdown of
                                          services. Subclasses should check if this is set by check-
                                          ing the `kill_switch` property for a True value in their
                                          core runtime. If True, the service should teardown and
                                          gracefully exit. This should only ever be set by the
                                          service runner and is a fatal/one-time event for the
                                          service.
    """
    super(PantsService, self).__init__()
    self.name = self.__class__.__name__
    self._kill_switch = kill_switch

  @property
  def kill_switch(self):
    return self._kill_switch.is_set()

  @abstractmethod
  def run(self):
    """The main entry-point for the service called by the service runner."""

  def terminate(self):
    self._kill_switch.set()
