# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import glob
import itertools
import os
import sys


from pants.backend.jvm.tasks.jvm_compile.anonymizer import Anonymizer
from pants.backend.jvm.tasks.jvm_compile.scala.zinc_analysis_parser import ZincAnalysisParser
from pants.util.dirutil import safe_mkdir


def main():
  """Anonymize a set of analysis files using the same replacements in all of them.

  This maintains enough consistency to make splitting/merging tests realistic.

  To run:

  ./pants py src/python/pants/backend/jvm/tasks/jvm_compile:anonymize_zinc_analysis \
    <wordfile> <classes dir in analysis files> <analysis file glob 1> <analysis file glob 2> ...
  """
  word_file = sys.argv[1]
  classes_dir = sys.argv[2]
  analysis_files = list(itertools.chain.from_iterable([glob.glob(p) for p in sys.argv[3:]]))

  with open(word_file, 'r') as infile:
    word_list = infile.read().split()
  anonymizer = Anonymizer(word_list)
  for analysis_file in analysis_files:
    analysis = ZincAnalysisParser(classes_dir).parse_from_path(analysis_file)
    analysis.anonymize(anonymizer)
    output_dir = os.path.join(os.path.dirname(analysis_file), 'anon')
    safe_mkdir(output_dir)
    anonymized_filename = anonymizer.convert(os.path.basename(analysis_file))
    analysis.write_to_path(os.path.join(output_dir, anonymized_filename))
  anonymizer.check_for_comprehensiveness()

if __name__ == '__main__':
  main()
