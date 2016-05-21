# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.zinc.zinc_analysis_diff import ZincAnalysisElementDiff
from pants.backend.jvm.zinc.zinc_analysis_element import ZincAnalysisElement


class CompileSetup(ZincAnalysisElement):
  headers = ('output mode', 'output directories', 'compile options', 'javac options',
             'compiler version', 'compile order', 'name hashing')

  # Output directories can obviously contain directories under pants_home. Compile/javac options may
  # refer to directories under pants_home.
  pants_home_anywhere = ('output directories', 'compile options', 'javac options')

  def __init__(self, args):
    # Most sections in CompileSetup are arrays represented as maps from index to item:
    #   0 -> item0
    #   1 -> item1
    #   ...
    #
    # We ensure these are sorted, in case any reading code makes assumptions about the order.
    # These are very small sections, so there's no performance impact to sorting them.
    super(CompileSetup, self).__init__(args, always_sort=True)
    (self.output_mode, self.output_dirs, self.compile_options, self.javac_options,
     self.compiler_version, self.compile_order, self.name_hashing) = self.args

  def translate(self, token_translator):
    self.translate_values(token_translator, self.output_dirs)
    for k, vs in list(self.compile_options.items()):  # Make a copy, so we can del as we go.
      # Remove mentions of custom plugins.
      for v in vs:
        if v.startswith(b'-Xplugin') or v.startswith(b'-P'):
          del self.compile_options[k]


class Relations(ZincAnalysisElement):
  headers = (b'products', b'binary dependencies',
             # TODO: The following 4 headers will go away after SBT completes the
             # transition to the new headers (the 4 after that).
             b'direct source dependencies', b'direct external dependencies',
             b'public inherited source dependencies', b'public inherited external dependencies',
             b'member reference internal dependencies', b'member reference external dependencies',
             b'inheritance internal dependencies', b'inheritance external dependencies',
             b'class names', b'used names')

  # Products are src->classfile, binary dependencies are src->jarfile, source/internal dependencies are src->src,
  # TODO: Check if 'used names' really needs to be in pants_home_anywhere, or can it be in pants_home_prefix_only?
  pants_home_anywhere = (b'products', b'binary dependencies',
                         b'direct source dependencies', b'public inherited source dependencies',
                         b'member reference internal dependencies', b'inheritance internal dependencies',
                         b'used names')
  # External dependencies and class names are src->fqcn.
  pants_home_prefix_only = (b'direct external dependencies', b'public inherited external dependencies',
                            b'member reference external dependencies', b'inheritance external dependencies',
                            b'class names')
  # Binary dependencies are src->jarfile, and that jarfile might be under the jvm home.
  java_home_anywhere = (b'binary dependencies',)

  def __init__(self, args):
    super(Relations, self).__init__(args)
    (self.src_prod, self.binary_dep,
     self.internal_src_dep, self.external_dep,
     self.internal_src_dep_pi, self.external_dep_pi,
     self.member_ref_internal_dep, self.member_ref_external_dep,
     self.inheritance_internal_dep, self.inheritance_external_dep,
     self.classes, self.used) = self.args

  def translate(self, token_translator):
    for a in self.args:
      self.translate_values(token_translator, a)
      self.translate_keys(token_translator, a)


class Stamps(ZincAnalysisElement):
  headers = (b'product stamps', b'source stamps', b'binary stamps', b'class names')

  # All sections are src/class/jar file->stamp.
  pants_home_prefix_only = headers
  # Only these sections can reference jar files under the jvm home.
  java_home_prefix_only = (b'binary stamps', b'class names')

  def __init__(self, args):
    super(Stamps, self).__init__(args)
    (self.products, self.sources, self.binaries, self.classnames) = self.args

  def translate(self, token_translator):
    for a in self.args:
      self.translate_keys(token_translator, a)
    self.translate_values(token_translator, self.classnames)

  # We make equality ignore the values in classnames: classnames is a map from
  # jar file to one representative class in that jar, and the representative can change.
  # However this doesn't affect any useful aspect of the analysis, so we ignore it.
  def diff(self, other):
    return ZincAnalysisElementDiff(self, other, keys_only_headers=('class names', ))

  def __eq__(self, other):
    return (self.products, self.sources, self.binaries, set(self.classnames.keys())) == \
           (other.products, other.sources, other.binaries, set(other.classnames.keys()))

  def __hash__(self):
    return hash((self.products, self.sources, self.binaries, self.classnames.keys()))


class APIs(ZincAnalysisElement):
  inline_vals = False

  headers = (b'internal apis', b'external apis')

  # Internal apis are src->blob, but external apis are fqcn->blob, so we don't need to rebase them.
  pants_home_prefix_only = (b'internal apis',)

  def __init__(self, args):
    super(APIs, self).__init__(args)
    (self.internal, self.external) = self.args

  def translate(self, token_translator):
    for a in self.args:
      self.translate_base64_values(token_translator, a)
      self.translate_keys(token_translator, a)


class SourceInfos(ZincAnalysisElement):
  inline_vals = False

  headers = (b'source infos', )

  # Source infos are src->blob.
  pants_home_prefix_only = headers

  def __init__(self, args):
    super(SourceInfos, self).__init__(args)
    (self.source_infos, ) = self.args

  def translate(self, token_translator):
    for a in self.args:
      self.translate_base64_values(token_translator, a)
      self.translate_keys(token_translator, a)


class Compilations(ZincAnalysisElement):
  headers = (b'compilations', )

  def __init__(self, args):
    super(Compilations, self).__init__(args)
    (self.compilations, ) = self.args
    # Compilations aren't useful and can accumulate to be huge and drag down parse times.
    # We clear them here to prevent them propagating through splits/merges.
    self.compilations.clear()

  def translate(self, token_translator):
    pass
