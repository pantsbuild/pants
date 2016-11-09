# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.zinc.zinc_analysis_element import ZincAnalysisElement


class CompileSetup(ZincAnalysisElement):
  headers = ('output mode', 'output directories', 'classpath options', 'compile options', 'javac options',
             'compiler version', 'compile order', 'name hashing', 'skip Api storing', 'extra')

  # Output directories can obviously contain directories under pants_home. Compile/javac options may
  # refer to directories under pants_home.
  pants_home_anywhere = ('output directories', 'classpath options')

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
     self.compiler_version, self.compile_order, self.name_hashing, self.extra) = self.args

  def translate(self, token_translator):
    self.translate_values(token_translator, self.output_dirs)
    for k, vs in list(self.compile_options.items()):  # Make a copy, so we can del as we go.
      # Remove mentions of custom plugins.
      for v in vs:
        if v.startswith(b'-Xplugin') or v.startswith(b'-P'):
          del self.compile_options[k]


class Relations(ZincAnalysisElement):
  headers = (b'products', b'library dependencies',  b'library class names',
             b'member reference internal dependencies', b'member reference external dependencies',
             b'inheritance internal dependencies', b'inheritance external dependencies',
             b'local internal inheritance dependencies', b'local external inheritance dependencies',
             b'class names', b'used names', b'product class names',)

  # Products are src->classfile, library dependencies are src->jarfile, source/internal dependencies are src->src,
  # TODO: Check if 'used names' really needs to be in pants_home_anywhere, or can it be in pants_home_prefix_only?
  pants_home_anywhere = (b'products', b'library dependencies',
                         b'inheritance internal dependencies')
  # External dependencies and class names are src->fqcn.
  pants_home_prefix_only = (b'library class names',
                            b'class names')
  # Library dependencies are src->jarfile, and that jarfile might be under the jvm home.
  java_home_anywhere = (b'library class names',
                        b'library dependencies',)

  def __init__(self, args):
    super(Relations, self).__init__(args)
    (self.src_prod, self.binary_dep,
     self.member_ref_internal_dep, self.member_ref_external_dep,
     self.inheritance_internal_dep, self.inheritance_external_dep,
     self.local_inheritance_internal_dep, self.local_inheritance_external_dep,
     self.classes, self.used, self.binary_classes) = self.args

  def translate(self, token_translator):
    for a in self.args:
      self.translate_values(token_translator, a)
      self.translate_keys(token_translator, a)


class Stamps(ZincAnalysisElement):
  headers = (b'product stamps', b'source stamps', b'binary stamps')

  pants_home_anywhere = headers
  # Only these sections can reference jar files under the jvm home.
  java_home_anywhere = (b'binary stamps')

  def __init__(self, args):
    super(Stamps, self).__init__(args)
    (self.products, self.sources, self.binaries, self.classnames) = self.args

  def translate(self, token_translator):
    for a in self.args:
      self.translate_keys(token_translator, a)
    self.translate_values(token_translator, self.classnames)

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
  pants_home_anywhere = headers

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
