# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractmethod


class ProcessHandler(object):
  """A simple class to abstract process handling calls using the same interface as subprocess.Popen.

  See SubprocessProcessHandler below for an example.
  """

  @abstractmethod
  def wait(self):
    raise NotImplementedError

  @abstractmethod
  def kill(self):
    raise NotImplementedError

  @abstractmethod
  def terminate(self):
    raise NotImplementedError

  @abstractmethod
  def poll(self):
    raise NotImplementedError


class SubprocessProcessHandler(ProcessHandler):
  """The simple passthrough class for a subprocess.Popen object."""

  def __init__(self, process):
    self._process = process

  def wait(self):
    return self._process.wait()

  def kill(self):
    return self._process.kill()

  def terminate(self):
    return self._process.terminate()

  def poll(self):
    return self._process.poll()
