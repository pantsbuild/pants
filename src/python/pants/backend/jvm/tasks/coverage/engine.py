# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractmethod

from pants.backend.jvm.targets.annotation_processor import AnnotationProcessor
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.util.meta import AbstractClass
from pants.util.objects import datatype


class CoverageEngine(AbstractClass):
  """The interface JVM code coverage processors must support.

  This is a stateful interface that will be called via the following sequence:

  1. instrument
  2. run_modifications
  3. report

  In this sequence, the `run_modifications` call in step 2 may occur multiple times if coverage data
  is being collected in parts. The `report` call in step 3 should be able to merge the results of
  these multiple runs.

  The coverage engine will be discarded after one exercise of this sequence; ie: a coverage engine
  is instantiated and used exactly once per `JUnitRun` task execution.
  """

  class RunModifications(datatype('RunModifications', ['classpath_prepend', 'extra_jvm_options'])):
    """Modifications that should be made to the java command where code coverage is collected.

    The `classpath_prepend` field should be an iterable of classpath elements to prepend to java
    command classpath.

    The `extra_jvm_options` should be a list of jvm options to include when executing the java
    command.
    """

    @classmethod
    def create(cls, classpath_prepend=None, extra_jvm_options=None):
      return cls(classpath_prepend=classpath_prepend or (),
                 extra_jvm_options=extra_jvm_options or [])

  @abstractmethod
  def instrument(self, output_dir):
    """Instruments JVM bytecode for coverage tracking.

    :param str output_dir: The path where report data should be generated under.
    """

  @abstractmethod
  def run_modifications(self, output_dir):
    """Describe modifications needed to the java command line that will run the instrumented code.

    :param str output_dir: The path where report data should be generated under.
    :returns: A description of run modifications.
    :rtype: :class:`CoverageEngine.RunModifications`
    """

  @abstractmethod
  def report(self, output_dir, execution_failed_exception=None):
    """Generate a report of code coverage.

    :param str output_dir: The path where report data should be generated under.
    :param Exception execution_failed_exception: If execution of the instrumented code failed, the
                                                 exception describing the failure.
    :returns: The path to the generated report iff it should be opened for the end user.
    :rtype: str
    """

  @staticmethod
  def is_coverage_target(tgt):
    # TODO: Does this actually need to check AnnotationProcessor targets? It does so at present
    # to preserve compatibility while migrating off target labels to type checks, but it seems
    # likely that inclusion of AnnotationProcessor in the past was in error, and unnecessary.
    return (isinstance(tgt, (AnnotationProcessor, JavaLibrary, ScalaLibrary))
            and not tgt.is_synthetic)


class NoCoverage(CoverageEngine):
  """A JVM code coverage processor that collects no code coverage data at all."""

  _NO_MODIFICATIONS = CoverageEngine.RunModifications.create()

  def instrument(self, output_dir):
    pass

  def run_modifications(self, output_dir):
    return self._NO_MODIFICATIONS

  def report(self, output_dir, execution_failed_exception=None):
    return None
