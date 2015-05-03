# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re

from zincutils.zinc_analysis_parser import ZincAnalysisParser as UnderlyingParser

from pants.backend.jvm.tasks.jvm_compile.analysis_parser import (AnalysisParser, ParseError,
                                                                 raise_on_eof)
from pants.backend.jvm.tasks.jvm_compile.scala.zinc_analysis import ZincAnalysis


class ZincAnalysisParser(AnalysisParser):
  """Parses a zinc analysis file.

  Implemented by delegating to an underlying zincutils.ZincAnalysisParser instance.
  """

  # Implement AnalysisParser properties.
  empty_test_header = 'products'
  current_test_header = ZincAnalysis.FORMAT_VERSION_LINE
  stamp_pattern = re.compile('[0-9]+')

  def __init__(self):
    self._underlying_parser = UnderlyingParser()

  # Implement AnalysisParser methods.

  def check_analysis(self, compile_context, deep):
    """Overrides superclass to implement `deep` checks of stamps and classfiles."""
    if not deep:
      super(ZincAnalysisParser, self).check_analysis(compile_context, deep)
    elif os.path.exists(compile_context.analysis_file):
      with open(compile_context.analysis_file, 'r') as infile:
        zinc_analysis = self.parse(infile)._underlying_analysis
        for product, stamps in zinc_analysis.stamps.products.items():
          # Parse the stamp entry for this product.
          assert len(stamps) == 1, ("Strange stamps!: {}".format(stamps))
          match = self.stamp_pattern.search(stamps[0])
          if not match:
            raise ParseError("Invalid stamps {} in {}".format(stamps, compile_context.analysis_file))
          stamp = int(match.group(0))

          # Compare the timestamp to the timestamp of the classfile: if this mismatches, zinc
          # will consider the file to have changed, and will invalidate its dependencies.
          product_mtime_millis = 1000 * int(os.stat(product).st_mtime)
          if stamp != product_mtime_millis:
            raise ParseError("Mismatched stamp for {}!: analysis: {} vs file: {}".format(
              compile_context.analysis_file,
              stamp,
              product_mtime_millis))

  def parse(self, infile):
    """Parse a ZincAnalysis instance from an open text file."""
    with raise_on_eof(infile):
      try:
        return ZincAnalysis(self._underlying_parser.parse(infile))
      except UnderlyingParser.ParseError as e:
        raise ParseError(e)

  def parse_products(self, infile, classes_dir):
    """An efficient parser of just the products section."""
    with raise_on_eof(infile):
      try:
        return self._underlying_parser.parse_products(infile)
      except UnderlyingParser.ParseError as e:
        raise ParseError(e)

  def parse_deps(self, infile, classpath_indexer, classes_dir):
    with raise_on_eof(infile):
      try:
        return self._underlying_parser.parse_deps(infile, classes_dir)
      except UnderlyingParser.ParseError as e:
        raise ParseError(e)
