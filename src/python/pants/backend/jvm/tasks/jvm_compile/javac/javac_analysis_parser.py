# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)


class JavacAnalysisParser(object):

  def parse(self, infile):
    pass

  def parse_products(self, infile, classes_dir):
    pass

  def parse_deps(self, infile):
    pass

  def rebase(self, infile, outfile, pants_home_from, pants_home_to, java_home=None):
    pass

  def rebase_from_path(self, infile_path, outfile_path, rebase_mappings, java_home=None):
    pass

  def parse_deps_from_path(self, infile_path):
    pass
