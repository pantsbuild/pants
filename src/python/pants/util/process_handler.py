# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractmethod


class ProcessHandler(object):
  @abstractmethod
  def wait(self):
    raise NotImplementedError

  @abstractmethod
  def kill(self):
    raise NotImplementedError

  @abstractmethod
  def terminate(self):
    raise NotImplementedError
