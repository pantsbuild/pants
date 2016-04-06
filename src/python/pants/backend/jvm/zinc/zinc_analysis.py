# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import itertools
from collections import defaultdict

import six

from pants.backend.jvm.zinc.zinc_analysis_element_types import (APIs, Compilations, CompileSetup,
                                                                Relations, SourceInfos, Stamps)


class ZincAnalysis(object):
  """Parsed representation of a zinc analysis.

  Note also that all files in keys/values are full-path, just as they appear in the analysis file.
  If you want paths relative to the build root or the classes dir or whatever, you must compute
  those yourself.
  """

  FORMAT_VERSION_LINE = b'format version: 5\n'

  @classmethod
  def merge(cls, analyses):
    # Note: correctly handles "internalizing" external deps that must be internal post-merge.

    # "Merge" compile setup. We assume that all merged analyses have the same setup, so we just take the
    # setup of the first analysis. TODO: Validate that all analyses have the same setup.
    compile_setup = analyses[0].compile_setup if len(analyses) > 0 else CompileSetup((defaultdict(list), ))

    # Merge relations.
    src_prod = ZincAnalysis._merge_disjoint_dicts([a.relations.src_prod for a in analyses])
    binary_dep = ZincAnalysis._merge_disjoint_dicts([a.relations.binary_dep for a in analyses])
    classes = ZincAnalysis._merge_disjoint_dicts([a.relations.classes for a in analyses])
    used = ZincAnalysis._merge_disjoint_dicts([a.relations.used for a in analyses])

    class_to_source = dict((v, k) for k, vs in classes.items() for v in vs)

    def merge_dependencies(internals, externals):
      internal = defaultdict(list)
      external = defaultdict(list)

      naive_internal = ZincAnalysis._merge_disjoint_dicts(internals)
      naive_external = ZincAnalysis._merge_disjoint_dicts(externals)

      # Note that we take care not to create empty values in internal.
      for k, vs in six.iteritems(naive_internal):
        if vs:
          internal[k].extend(vs)  # Ensure a new list.

      for k, vs in six.iteritems(naive_external):
        # class->source is many->one, so make sure we only internalize a source once.
        internal_k = set(internal.get(k, []))
        for v in vs:
          vfile = class_to_source.get(v)
          if vfile and vfile in src_prod:
            internal_k.add(vfile)  # Internalized.
          else:
            external[k].append(v)  # Remains external.
        if internal_k:
          internal[k] = list(internal_k)
      return internal, external

    internal, external = merge_dependencies(
      [a.relations.internal_src_dep for a in analyses],
      [a.relations.external_dep for a in analyses])

    internal_pi, external_pi = merge_dependencies(
      [a.relations.internal_src_dep_pi for a in analyses],
      [a.relations.external_dep_pi for a in analyses])

    member_ref_internal, member_ref_external = merge_dependencies(
      [a.relations.member_ref_internal_dep for a in analyses],
      [a.relations.member_ref_external_dep for a in analyses])

    inheritance_internal, inheritance_external = merge_dependencies(
      [a.relations.inheritance_internal_dep for a in analyses],
      [a.relations.inheritance_external_dep for a in analyses])

    relations = Relations((src_prod, binary_dep,
                           internal, external,
                           internal_pi, external_pi,
                           member_ref_internal, member_ref_external,
                           inheritance_internal, inheritance_external,
                           classes, used))

    # Merge stamps.
    products = ZincAnalysis._merge_disjoint_dicts([a.stamps.products for a in analyses])
    sources = ZincAnalysis._merge_disjoint_dicts([a.stamps.sources for a in analyses])
    binaries = ZincAnalysis._merge_overlapping_dicts([a.stamps.binaries for a in analyses])
    classnames = ZincAnalysis._merge_disjoint_dicts([a.stamps.classnames for a in analyses])
    stamps = Stamps((products, sources, binaries, classnames))

    # Merge APIs.
    internal_apis = ZincAnalysis._merge_disjoint_dicts([a.apis.internal for a in analyses])
    naive_external_apis = ZincAnalysis._merge_disjoint_dicts([a.apis.external for a in analyses])
    external_apis = defaultdict(list)
    for k, vs in six.iteritems(naive_external_apis):
      kfile = class_to_source.get(k)
      if kfile and kfile in src_prod:
        internal_apis[kfile] = vs  # Internalized.
      else:
        external_apis[k] = vs  # Remains external.
    apis = APIs((internal_apis, external_apis))

    # Merge source infos.
    source_infos = SourceInfos((ZincAnalysis._merge_disjoint_dicts([a.source_infos.source_infos for a in analyses]), ))

    # Merge compilations.
    compilation_vals = sorted(set([x[0] for a in analyses for x in six.itervalues(a.compilations.compilations)]))
    compilations_dict = defaultdict(list)
    for i, v in enumerate(compilation_vals):
      compilations_dict[b'{:03}'.format(int(i))] = [v]
    compilations = Compilations((compilations_dict, ))

    return ZincAnalysis(compile_setup, relations, stamps, apis, source_infos, compilations)

  @staticmethod
  def _merge_disjoint_dicts(dicts):
    """Merges multiple dicts with disjoint key sets into one.

    May also be used when we don't care which value is picked for a key that appears more than once.
    """
    ret = defaultdict(list)
    for d in dicts:
      ret.update(d)
    return ret

  @staticmethod
  def _merge_overlapping_dicts(dicts):
    """Merges multiple, possibly overlapping, dicts into one.

    If a key exists in more than one dict, takes the largest value in dictionary order.
    This is useful when the values are singleton stamp lists of the form ['lastModified(XXXXXXXX)'],
    as it will lead to taking the most recent modification time.
    """
    ret = defaultdict(list)
    for d in dicts:
      for k, v in six.iteritems(d):
        if k not in ret or ret[k] < v:
          ret[k] = v
    return ret

  def __init__(self, compile_setup, relations, stamps, apis, source_infos, compilations):
    (self.compile_setup, self.relations, self.stamps, self.apis, self.source_infos, self.compilations) = \
      (compile_setup, relations, stamps, apis, source_infos, compilations)

  def diff(self, other):
    """Returns a list of element diffs, one per element where self and other differ."""
    element_diffs = []
    for self_elem, other_elem in zip(
            (self.compile_setup, self.relations, self.stamps, self.apis,
             self.source_infos, self.compilations),
            (other.compile_setup, other.relations, other.stamps, other.apis,
             other.source_infos, other.compilations)):
      element_diff = self_elem.diff(other_elem)
      if element_diff.is_different():
        element_diffs.append(element_diff)
    return element_diffs

  def sources(self):
    return self.stamps.sources.keys()

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

  def split(self, splits, catchall=False):
    # Note: correctly handles "externalizing" internal deps that must be external post-split.
    splits = [set(x) for x in splits]  # Ensure sets, for performance.
    if catchall:
      # Even empty sources with no products have stamps.
      remainder_sources = set(self.sources()).difference(*splits)
      splits.append(remainder_sources)  # The catch-all

    # The inner functions are primarily for ease of performance profiling.

    # For historical reasons, external deps are specified as src->class while internal deps are
    # specified as src->src.  So when splitting we need to pick a representative.  We must pick
    # consistently, so we take the first class name in alphanumeric order.
    def make_representatives():
      representatives = {k: min(vs) for k, vs in six.iteritems(self.relations.classes)}
      return representatives
    representatives = make_representatives()

    # Split the source, binary and classes keys in our relations structs.
    # Subsequent operations need this data.
    def split_relation_keys():
      src_prod_splits = self._split_dict(self.relations.src_prod, splits)
      binary_dep_splits = self._split_dict(self.relations.binary_dep, splits)
      classes_splits = self._split_dict(self.relations.classes, splits)
      return src_prod_splits, binary_dep_splits, classes_splits
    src_prod_splits, binary_dep_splits, classes_splits = split_relation_keys()

    # Split relations.
    def split_relations():
      # Split a single pair of (internal, external) dependencies.
      def _split_dependencies(all_internal, all_external):
        internals = []
        externals = []

        naive_internals = self._split_dict(all_internal, splits)
        naive_externals = self._split_dict(all_external, splits)

        for naive_internal, naive_external, split in zip(naive_internals, naive_externals, splits):
          internal = defaultdict(list)
          external = defaultdict(list)

          # Note that we take care not to create empty values in external.
          for k, vs in six.iteritems(naive_external):
            if vs:
              external[k].extend(vs)  # Ensure a new list.

          for k, vs in six.iteritems(naive_internal):
            for v in vs:
              if v in split:
                internal[k].append(v)  # Remains internal.
              else:
                external[k].append(representatives[v])  # Externalized.
          internals.append(internal)
          externals.append(external)
        return internals, externals

      internal_splits, external_splits = \
        _split_dependencies(self.relations.internal_src_dep, self.relations.external_dep)
      internal_pi_splits, external_pi_splits = \
        _split_dependencies(self.relations.internal_src_dep_pi, self.relations.external_dep_pi)

      member_ref_internal_splits, member_ref_external_splits = \
        _split_dependencies(self.relations.member_ref_internal_dep, self.relations.member_ref_external_dep)
      inheritance_internal_splits, inheritance_external_splits = \
        _split_dependencies(self.relations.inheritance_internal_dep, self.relations.inheritance_external_dep)
      used_splits = self._split_dict(self.relations.used, splits)

      relations_splits = []
      for args in zip(src_prod_splits, binary_dep_splits,
                      internal_splits, external_splits,
                      internal_pi_splits, external_pi_splits,
                      member_ref_internal_splits, member_ref_external_splits,
                      inheritance_internal_splits, inheritance_external_splits,
                      classes_splits, used_splits):
        relations_splits.append(Relations(args))
      return relations_splits
    relations_splits = split_relations()

    # Split stamps.
    def split_stamps():
      stamps_splits = []
      sources_splits = self._split_dict(self.stamps.sources, splits)
      for src_prod, binary_dep, sources in zip(src_prod_splits, binary_dep_splits, sources_splits):
        products_set = set(itertools.chain(*six.itervalues(src_prod)))
        binaries_set = set(itertools.chain(*six.itervalues(binary_dep)))
        products, _ = self._restrict_dicts(products_set, self.stamps.products)
        binaries, classnames = self._restrict_dicts(binaries_set, self.stamps.binaries,
                                                    self.stamps.classnames)
        stamps_splits.append(Stamps((products, sources, binaries, classnames)))
      return stamps_splits
    stamps_splits = split_stamps()

    # Split apis.
    def split_apis():
      # Externalized deps must copy the target's formerly internal API.
      representative_to_internal_api = {}
      for src, rep in six.iteritems(representatives):
        representative_to_internal_api[rep] = self.apis.internal.get(src)

      internal_api_splits = self._split_dict(self.apis.internal, splits)

      external_api_splits = []
      for rel in relations_splits:
        external_api = {}
        for vs in six.itervalues(rel.external_dep):
          for v in vs:
            if v in representative_to_internal_api:  # This is an externalized dep.
              external_api[v] = representative_to_internal_api[v]
            else: # This is a dep that was already external.
              external_api[v] = self.apis.external[v]
        external_api_splits.append(external_api)

      apis_splits = []
      for args in zip(internal_api_splits, external_api_splits):
        apis_splits.append(APIs(args))
      return apis_splits
    apis_splits = split_apis()

    # Split source infos.
    def split_source_infos():
      source_info_splits = \
        [SourceInfos((x, )) for x in self._split_dict(self.source_infos.source_infos, splits)]
      return source_info_splits
    source_info_splits = split_source_infos()

    # Create the final ZincAnalysis instances from all these split pieces.
    def create_analyses():
      analyses = []
      for relations, stamps, apis, source_infos in zip(relations_splits, stamps_splits, apis_splits, source_info_splits):
        analyses.append(ZincAnalysis(self.compile_setup, relations, stamps, apis, source_infos, self.compilations))
      return analyses
    analyses = create_analyses()

    return analyses

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
  # splitting and merging, but not for actually reading into Zinc.
  def translate(self, token_translator):
    for element in [self.compile_setup, self.relations, self.stamps, self.apis,
                    self.source_infos, self.compilations]:
      element.translate(token_translator)

  def _split_dict(self, d, splits):
    """Split a dict by its keys.

    splits: A list of lists of keys.
    Returns one dict per split.
    """
    ret = []
    for split in splits:
      dict_split = defaultdict(list)
      for f in split:
        if f in d:
          dict_split[f] = d[f]
      ret.append(dict_split)
    return ret

  def _restrict_dicts(self, keys, dict1, dict2=None):
    """Returns a subdict of each input dict with its keys restricted to the given set.

    Assumes that iterating over keys is much faster than iterating over the dicts. So use this
    when keys is small compared to the total number of items in the dicts.

    Note: the interface is a bit odd, and would be more general if we allowed an arbitrary
    number of dicts. However in practice we only need this for 1 or 2 dicts, and this code
    runs faster than if we had to iterate over a list of dicts in an inner loop.
    """
    ret1 = {}
    ret2 = None if dict2 is None else {}
    for k in keys:
      if k in dict1:
        ret1[k] = dict1[k]
      if dict2 is not None and k in dict2:
        ret2[k] = dict2[k]
    return ret1, ret2
