# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)


class ZincAnalysis(object):
  """Parsed representation of a zinc analysis.

  Note also that all files in keys/values are full-path, just as they appear in the analysis file.
  If you want paths relative to the build root or the classes dir or whatever, you must compute
  those yourself.
  """

  FORMAT_VERSION_LINE = b'format version: 6\n'

  def __init__(self, compile_setup, relations, stamps, apis, source_infos, compilations):
    (self.compile_setup, self.relations, self.stamps, self.apis, self.source_infos, self.compilations) = \
      (compile_setup, relations, stamps, apis, source_infos, compilations)

  def is_equal_to(self, other):
    for self_element, other_element in zip(
        (self.compile_setup, self.relations, self.stamps, self.apis,
         self.source_infos, self.compilations),
        (other.compile_setup, other.relations, other.stamps, other.apis,
         other.source_infos, other.compilations)):
      if not self_element.is_equal_to(other_element):
        return False
    return True

  def __ne__(self, other):
    return not self.__eq__(other)

  def __hash__(self):
    return hash((self.compile_setup, self.relations, self.stamps, self.apis,
                 self.source_infos, self.compilations))

  def write_to_path(self, outfile_path):
    with open(outfile_path, 'wb') as outfile:
      self.write(outfile)

  def write(self, outfile):
    outfile.write(ZincAnalysis.FORMAT_VERSION_LINE)
    self.compile_setup.write(outfile)
    self.relations.write(outfile)
    self.stamps.write(outfile)
    self.apis.write(outfile)
    self.source_infos.write(outfile)
    self.compilations.write(outfile)

  # Translate the contents of this analysis. Useful for creating anonymized test data.
  # Note that the resulting file is not a valid analysis, as the base64-encoded serialized objects
  # will be replaced with random base64 strings. So these are useful for testing analysis parsing,
  # but not for actually reading into Zinc.
  def translate(self, token_translator):
    for element in [self.compile_setup, self.relations, self.stamps, self.apis,
                    self.source_infos, self.compilations]:
      element.translate(token_translator)
