# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import threading
from abc import abstractmethod

from pants.util.meta import AbstractClass


class PantsService(AbstractClass):
  """Pants daemon service base class."""

  class ServiceError(Exception): pass

  def __init__(self):
    super(PantsService, self).__init__()
    self.name = self.__class__.__name__
    self._kill_switch = threading.Event()

  @property
  def is_killed(self):
    """A `threading.Event`-checking property to facilitate graceful shutdown of services.

    Subclasses should check this property for a True value in their core runtime. If True, the
    service should teardown and gracefully exit. This represents a fatal/one-time event for the
    service.
    """
    return self._kill_switch.is_set()

  def setup(self):
    """Called before `run` to allow for service->service or other side-effecting setup."""

  @abstractmethod
  def run(self):
    """The main entry-point for the service called by the service runner."""

  def terminate(self):
    """Called upon service teardown."""
    self._kill_switch.set()
