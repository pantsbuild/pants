# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)


class CompileContext(object):
  """A context for the compilation of a target.

  This can be used to differentiate between a partially completed compile in a temporary location
  and a finalized compile in its permanent location.
  """
  def __init__(self, target, analysis_file, classes_dir, sources):
    self.target = target
    self.analysis_file = analysis_file
    self.classes_dir = classes_dir
    self.sources = sources

  @property
  def _id(self):
    return (self.target, self.analysis_file, self.classes_dir)

  def __eq__(self, other):
    return self._id == other._id

  def __ne__(self, other):
    return self._id != other._id

  def __hash__(self):
    return hash(self._id)


class IsolatedCompileContext(CompileContext):
  """Extends CompileContext to add a jar location."""
  def __init__(self, target, analysis_file, classes_dir, jar_file, sources):
    super(IsolatedCompileContext, self).__init__(target, analysis_file, classes_dir, sources)
    self.jar_file = jar_file
