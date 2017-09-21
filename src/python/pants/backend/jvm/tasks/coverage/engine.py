# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractmethod, abstractproperty

from pants.util.meta import AbstractClass


class CoverageEngine(AbstractClass):
  """The interface JVM code coverage processors must support."""

  @abstractmethod
  def instrument(self):
    """Instruments JVM bytecode for coverage tracking."""

  @abstractmethod
  def report(self, execution_failed_exception=None):
    """Generate a report of code coverage and return the path of the report.

    :param Exception execution_failed_exception: If execution of the instrumented code failed, the
                                                 exception describing the failure.
    """

  @abstractmethod
  def maybe_open_report(self):
    """Open the code coverage report if requested by the end user."""

  @abstractproperty
  def classpath_prepend(self):
    """Return an iterable of classpath elements to prepend to the JVM code execution classpath."""

  @abstractproperty
  def classpath_append(self):
    """Return an iterable of classpath elements to append to the JVM code execution classpath."""

  @abstractproperty
  def extra_jvm_options(self):
    """Return an list of jvm options to use executing JVM code in order to collect coverage data."""


class NoCoverage(CoverageEngine):
  """A JVM code coverage processor that collects no code coverage data at all."""

  def instrument(self):
    pass

  def report(self, execution_failed_exception=None):
    return None

  def maybe_open_report(self):
    pass

  @property
  def classpath_prepend(self):
    return ()

  @property
  def classpath_append(self):
    return ()

  @property
  def extra_jvm_options(self):
    return []
