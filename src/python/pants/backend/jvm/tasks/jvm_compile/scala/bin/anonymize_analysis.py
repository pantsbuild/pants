# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import glob
import itertools
import os
import sys

from pants.backend.jvm.tasks.jvm_compile.anonymizer import TranslationCapturer
from pants.backend.jvm.tasks.jvm_compile.scala.zinc_analysis_parser import ZincAnalysisParser
from pants.util.dirutil import safe_mkdir


def main():
  """Anonymize a set of analysis files using the same replacements in all of them.

  This maintains enough consistency to make splitting/merging tests realistic.
  In particular, it preserves dictionary order, so that representative class selection
  is consistent after anonymization.

  To run:

  ./pants run src/python/pants/backend/jvm/tasks/jvm_compile:anonymize_zinc_analysis -- \
    <wordfile> <classes dir in analysis files> <analysis file glob 1> <analysis file glob 2> ...

  Output will be in a directory called 'anon' under the directory of each input analysis file.

  An easy way to generate a wordfile is to download SCOWL (http://wordlist.aspell.net/) and look
  at final/english-words.*.  A good wordfile can be had thus:

  for f in english-words.*; do cat $f >> wordfile; done
  egrep '^[a-z]{4}[a-z]*$' wordfile > wordfile.filtered

  Note that the larger the number at the end of the filename the rarer the words in it, so if you want
  to avoid rare words, manually cat the lowest few files into wordfile, until you have enough words.
  """
  word_file = sys.argv[1]
  classes_dir = sys.argv[2]
  analysis_files = list(itertools.chain.from_iterable([glob.glob(p) for p in sys.argv[3:]]))

  with open(word_file, 'r') as infile:
    word_list = infile.read().split()

  # First pass: Capture all words that need translating.
  translation_capturer = TranslationCapturer(word_list)
  for analysis_file in analysis_files:
    analysis = ZincAnalysisParser(classes_dir).parse_from_path(analysis_file)
    analysis.translate(translation_capturer)
    translation_capturer.convert(os.path.basename(analysis_file))
  translation_capturer.check_for_comprehensiveness()

  # Second pass: Actually translate, in order-preserving fashion.
  anonymizer = translation_capturer.get_order_preserving_anonymizer()
  for analysis_file in analysis_files:
    analysis = ZincAnalysisParser(classes_dir).parse_from_path(analysis_file)
    analysis.translate(anonymizer)
    output_dir = os.path.join(os.path.dirname(analysis_file), 'anon')
    safe_mkdir(output_dir)
    anonymized_filename = anonymizer.convert(os.path.basename(analysis_file))
    analysis.write_to_path(os.path.join(output_dir, anonymized_filename))
  anonymizer.check_for_comprehensiveness()

if __name__ == '__main__':
  main()
