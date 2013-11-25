from collections import defaultdict
import json
import os
import re
import itertools
from twitter.pants import TaskError, get_buildroot


class ParseError(TaskError):
  pass


class AnalysisElement(object):
  """Encapsulates one part of the analysis.

  Subclasses specify which section headers comprise this part. Note that data in these objects is
  just text, possibly split on lines or '->'.
  """
  headers = ()  # Override in subclasses.

  @classmethod
  def parse(cls, lines_iter):
    return cls(Util.parse_multiple_sections(lines_iter, cls.headers))

  @classmethod
  def from_json_obj(cls, obj):
    return cls([obj[header] for header in cls.headers])

  def __init__(self, args):
    # Subclasses can alias the elements of self.args in their own __init__, for convenience.
    self.args = args

  def write(self, outfile, inline_vals=True):
    Util.write_multiple_sections(outfile, self.headers, self.args, inline_vals)


class AnalysisJSONEncoder(json.JSONEncoder):
  """A custom encoder for writing analysis elements as JSON.

  Not currently used, but might be useful in the future, e.g., for creating javascript-y
  analysis browsing tools.
  """
  def default(self, obj):
    if isinstance(obj, AnalysisElement):
      ret = {}
      for h, a in zip(obj.__class__.headers, obj.args):
        ret[h] = a
      return ret
    else:
      super(AnalysisJSONEncoder, self).default(obj)


class Analysis(object):
  """Parsed representation of a zinc analysis.

  Note also that all files in keys/values are full-path, just as they appear in the analysis file.
  If you want paths relative to the build root or the classes dir or whatever, you must compute
  those yourself.
  """
  @staticmethod
  def parse_from_path(infile_path):
    """Parse an Analysis instance from a text file."""
    with open(infile_path, 'r') as infile:
      return Analysis.parse(infile)

  @staticmethod
  def parse_json_from_path(infile_path):
    """Parse an Analysis instance from a JSON file."""
    with open(infile_path, 'r') as infile:
      return Analysis.parse_from_json(infile)

  @staticmethod
  def parse(infile):
    """Parse an Analysis instance from an open text file."""
    lines_iter = infile
    Analysis._verify_version(lines_iter)
    relations = Relations.parse(lines_iter)
    stamps = Stamps.parse(lines_iter)
    apis = APIs.parse(lines_iter)
    source_infos = SourceInfos.parse(lines_iter)
    compilations = Compilations.parse(lines_iter)
    compile_setup = CompileSetup.parse(lines_iter)
    return Analysis(relations, stamps, apis, source_infos, compilations, compile_setup)

  @staticmethod
  def parse_from_json(infile):
    """Parse an Analysis instance from an open JSON file."""
    obj = json.load(infile)
    relations = Relations.from_json_obj(obj['relations'])
    stamps = Stamps.from_json_obj(obj['stamps'])
    apis = APIs.from_json_obj(obj['apis'])
    source_infos = SourceInfos.from_json_obj(obj['source infos'])
    compilations = Compilations.from_json_obj(obj['compilations'])
    compile_setup = Compilations.from_json_obj(obj['compile setup'])
    return Analysis(relations, stamps, apis, source_infos, compilations, compile_setup)

  @staticmethod
  def parse_products_from_path(infile_path):
    with open(infile_path, 'r') as infile:
      return Analysis.parse_products(infile)

  @staticmethod
  def parse_products(infile):
    """An efficient parser of just the products section."""
    Analysis._verify_version(infile)
    return Analysis._find_repeated_at_header(infile, 'products')

  @staticmethod
  def parse_deps_from_path(infile_path):
    with open(infile_path, 'r') as infile:
      return Analysis.parse_deps(infile)

  @staticmethod
  def parse_deps(infile):
    """An efficient parser of just the binary, source and external deps sections.

    Returns a dict of src -> list of deps, where each item in deps is either a binary dep,
    source dep or external dep, i.e., either a source file, a class file or a jar file.

    All paths are absolute.
    """
    Analysis._verify_version(infile)
    # Note: relies on the fact that these headers appear in this order in the file.
    bin_deps = Analysis._find_repeated_at_header(infile, 'binary dependencies')
    src_deps = Analysis._find_repeated_at_header(infile, 'source dependencies')
    ext_deps = Analysis._find_repeated_at_header(infile, 'external dependencies')
    return Util.merge_dicts([bin_deps, src_deps, ext_deps])

  @staticmethod
  def _find_repeated_at_header(lines_iter, header):
    header_line = header + ':\n'
    while lines_iter.next() != header_line:
      pass
    return Util.parse_section(lines_iter, expected_header=None)

  FORMAT_VERSION_LINE = 'format version: 1\n'
  @staticmethod
  def _verify_version(lines_iter):
    version_line = lines_iter.next()
    if version_line != Analysis.FORMAT_VERSION_LINE:
      raise TaskError('Unrecognized version line: ' + version_line)

  @staticmethod
  def rebase(input_analysis_path, output_analysis_path, rebasings):
    """Rebase file paths in an analysis file.

    rebasings: a list of path prefix pairs [from_prefix, to_prefix] to rewrite.

    Note that this is implemented using string.replace, for efficiency, so this will
    actually just replace everywhere, not just path prefixes. However in practice this
    makes no difference, and the performance gains are considerable.
    """
    # TODO: Can make this more efficient if needed, e.g., we know which sections contain
    # which path prefixes. But for now this is fine.
    with open(input_analysis_path, 'r') as infile:
      txt = infile.read()
    for rebase_from, rebase_to in rebasings:
      txt = txt.replace(rebase_from, rebase_to)
    with open(output_analysis_path, 'w') as outfile:
      outfile.write(txt)

  @staticmethod
  def split_to_paths(analysis_path, split_path_pairs, catchall_path=None):
    """Split an analysis file.

    split_path_pairs: A list of pairs (split, output_path) where split is a list of source files
    whose analysis is to be split out into output_path. The source files may either be
    absolute paths, or relative to the build root.

    If catchall_path is specified, the analysis for any sources not mentioned in the splits is
    split out to that path.
    """
    analysis = Analysis.parse_from_path(analysis_path)
    splits = [x[0] for x in split_path_pairs]
    split_analyses = analysis.split(splits, catchall_path is not None)
    output_paths = [x[1] for x in split_path_pairs]
    if catchall_path is not None:
      output_paths.append(catchall_path)
    for analysis, path in zip(split_analyses, output_paths):
      analysis.write_to_path(path)

  @staticmethod
  def merge_from_paths(analysis_paths, merged_analysis_path):
    """Merge multiple analysis files into one."""
    analyses = [Analysis.parse_from_path(path) for path in analysis_paths]
    merged_analysis = Analysis.merge(analyses)
    merged_analysis.write_to_path(merged_analysis_path)

  @staticmethod
  def merge(analyses):
    """Merge multiple Analysis instances into one."""
    # Note: correctly handles "internalizing" external deps that must be internal post-merge.

    # Merge relations.
    src_prod = Util.merge_dicts([a.relations.src_prod for a in analyses])
    binary_dep = Util.merge_dicts([a.relations.binary_dep for a in analyses])
    classes = Util.merge_dicts([a.relations.classes for a in analyses])

    class_to_source = dict((v, k) for k, vs in classes.iteritems() for v in vs)

    def merge_dependencies(internals, externals):
      internal = Util.merge_dicts(internals)
      naive_external = Util.merge_dicts(externals)
      external = defaultdict(list)
      for k, vs in naive_external.iteritems():
        for v in vs:
          vfile = class_to_source.get(v)
          if vfile and vfile in src_prod:
            internal[k].append(vfile)  # Internalized.
          else:
            external[k].append(v)  # Remains external.
      return internal, external

    internal, external = merge_dependencies([a.relations.internal_src_dep for a in analyses],
                                            [a.relations.external_dep for a in analyses])

    internal_pi, external_pi = merge_dependencies([a.relations.internal_src_dep_pi for a in analyses],
                                                  [a.relations.external_dep_pi for a in analyses])
    relations = Relations((src_prod, binary_dep, internal, external, internal_pi, external_pi, classes))

    # Merge stamps.
    products = Util.merge_dicts([a.stamps.products for a in analyses])
    sources = Util.merge_dicts([a.stamps.sources for a in analyses])
    binaries = Util.merge_dicts([a.stamps.binaries for a in analyses])
    classnames = Util.merge_dicts([a.stamps.classnames for a in analyses])
    stamps = Stamps((products, sources, binaries, classnames))

    # Merge APIs.
    internal_apis = Util.merge_dicts([a.apis.internal for a in analyses])
    naive_external_apis = Util.merge_dicts([a.apis.external for a in analyses])
    external_apis = defaultdict(list)
    for k, vs in naive_external_apis.iteritems():
      kfile = class_to_source[k]
      if kfile in src_prod:
        internal_apis[kfile] = vs  # Internalized.
      else:
        external_apis[k] = vs  # Remains external.
    apis = APIs((internal_apis, external_apis))

    # Merge source infos.
    source_infos = SourceInfos((Util.merge_dicts([a.source_infos.source_infos for a in analyses]), ))

    # Merge compilations.
    compilation_vals = sorted(set([x[0] for a in analyses for x in a.compilations.compilations.itervalues()]))
    compilations_dict = defaultdict(list)
    for i, v in enumerate(compilation_vals):
      compilations_dict['%03d' % i] = [v]
    compilations = Compilations((compilations_dict, ))

    compile_setup = analyses[0].compile_setup if len(analyses) > 0 else CompileSetup((defaultdict(list), ))
    return Analysis(relations, stamps, apis, source_infos, compilations, compile_setup)


  def __init__(self, relations, stamps, apis, source_infos, compilations, compile_setup):
    (self.relations, self.stamps, self.apis, self.source_infos, self.compilations, self.compile_setup) = \
      (relations, stamps, apis, source_infos, compilations, compile_setup)

  def write_to_path(self, outfile_path):
    with open(outfile_path, 'w') as outfile:
      self.write(outfile)

  def write_json_to_path(self, outfile_path):
    with open(outfile_path, 'w') as outfile:
      self.write_json(outfile)

  def write(self, outfile):
    outfile.write(Analysis.FORMAT_VERSION_LINE)
    self.relations.write(outfile)
    self.stamps.write(outfile)
    self.apis.write(outfile, inline_vals=False)
    self.source_infos.write(outfile, inline_vals=False)
    self.compilations.write(outfile, inline_vals=False)
    self.compile_setup.write(outfile, inline_vals=False)

  def write_json(self, outfile):
    obj = dict(zip(('relations', 'stamps', 'apis', 'source_infos', 'compilations', 'compile_setup'),
                   (self.relations, self.stamps, self.apis, self.source_infos, self.compilations, self.compile_setup)))
    json.dump(obj, outfile, cls=AnalysisJSONEncoder, sort_keys=True, indent=2)

  def split(self, splits, catchall=False):
    """Split the analysis according to splits, which is a list of K iterables of source files.

    If catchall is False, returns a list of K Analysis objects, one for each of the splits, in order.
    If catchall is True, returns K+1 Analysis objects, the last one containing the analysis for any
    remainder sources not mentioned in the K splits.
    """
    # Note: correctly handles "externalizing" internal deps that must be external post-split.
    buildroot = get_buildroot()
    splits = [set([s if os.path.isabs(s) else os.path.join(buildroot, s) for s in x]) for x in splits]
    if catchall:
      # Even empty sources with no products have stamps.
      all_sources = set(self.stamps.sources.keys()).difference(*splits)
      splits.append(all_sources)  # The catch-all

    # Split relations.
    src_prod_splits = Util.split_dict(self.relations.src_prod, splits)
    binary_dep_splits = Util.split_dict(self.relations.binary_dep, splits)
    classes_splits = Util.split_dict(self.relations.classes, splits)

    # For historical reasons, external deps are specified as src->class while internal deps are
    # specified as src->src. So we pick a representative class for each src.
    representatives = dict((k, min(vs)) for k, vs in self.relations.classes.iteritems())

    def split_dependencies(all_internal, all_external):
      naive_internals = Util.split_dict(all_internal, splits)
      naive_externals = Util.split_dict(all_external, splits)

      internals = []
      externals = []
      for naive_internal, external, split in zip(naive_internals, naive_externals, splits):
        internal = defaultdict(list)
        for k, vs in naive_internal.iteritems():
          for v in vs:
            if v in split:
              internal[k].append(v)  # Remains internal.
            else:
              external[k].append(representatives[v])  # Externalized.
        internals.append(internal)
        externals.append(external)
      return internals, externals

    internal_splits, external_splits = split_dependencies(self.relations.internal_src_dep, self.relations.external_dep)
    internal_pi_splits, external_pi_splits = split_dependencies(self.relations.internal_src_dep_pi, self.relations.external_dep_pi)

    relations_splits = []
    for args in zip(src_prod_splits, binary_dep_splits, internal_splits, external_splits,
                    internal_pi_splits, external_pi_splits, classes_splits):
      relations_splits.append(Relations(args))

    # Split stamps.
    stamps_splits = []
    for src_prod, binary_dep, split in zip(src_prod_splits, binary_dep_splits, splits):
      products_set = set(itertools.chain(*src_prod.values()))
      binaries_set = set(itertools.chain(*binary_dep.values()))
      products = dict((k, v) for k, v in self.stamps.products.iteritems() if k in products_set)
      sources = dict((k, v) for k, v in self.stamps.sources.iteritems() if k in split)
      binaries = dict((k, v) for k, v in self.stamps.binaries.iteritems() if k in binaries_set)
      classnames = dict((k, v) for k, v in self.stamps.classnames.iteritems() if k in binaries_set)
      stamps_splits.append(Stamps((products, sources, binaries, classnames)))

    # Split apis.
    naive_internal_api_splits = Util.split_dict(self.apis.internal, splits)
    naive_external_api_splits = Util.split_dict(self.apis.external, splits)

    internal_api_splits = []
    external_api_splits = []
    for naive_internal_apis, external_apis, split in \
      zip(naive_internal_api_splits, naive_external_api_splits, splits):
      internal_apis = defaultdict(list)
      for k, vs in naive_internal_apis.iteritems():
        if k in split:
          internal_apis[k] = vs  # Remains internal.
        else:
          external_apis[representatives[k]] = vs  # Externalized.
      internal_api_splits.append(internal_apis)
      external_api_splits.append(external_apis)

    apis_splits = []
    for args in zip(internal_api_splits, external_api_splits):
      apis_splits.append(APIs(args))

    # Split source infos.
    source_info_splits = [SourceInfos((x, )) for x in Util.split_dict(self.source_infos.source_infos, splits)]

    analyses = []
    for relations, stamps, apis, source_infos in zip(relations_splits, stamps_splits, apis_splits, source_info_splits):
      analyses.append(Analysis(relations, stamps, apis, source_infos, self.compilations, self.compile_setup))

    return analyses


class Relations(AnalysisElement):
  headers = ('products', 'binary dependencies', 'source dependencies', 'external dependencies',
             'public inherited source dependencies', 'public inherited external dependencies', 'class names')

  def __init__(self, args):
    super(Relations, self).__init__(args)
    (self.src_prod, self.binary_dep, self.internal_src_dep, self.external_dep,
     self.internal_src_dep_pi, self.external_dep_pi, self.classes) = self.args


class Stamps(AnalysisElement):
  headers = ('product stamps', 'source stamps', 'binary stamps', 'class names')

  def __init__(self, args):
    super(Stamps, self).__init__(args)
    (self.products, self.sources, self.binaries, self.classnames) = self.args


class APIs(AnalysisElement):
  headers = ('internal apis', 'external apis')

  def __init__(self, args):
    super(APIs, self).__init__(args)
    (self.internal, self.external) = self.args


class SourceInfos(AnalysisElement):
  headers = ("source infos", )

  def __init__(self, args):
    super(SourceInfos, self).__init__(args)
    (self.source_infos, ) = self.args


class Compilations(AnalysisElement):
  headers = ('compilations', )

  def __init__(self, args):
    super(Compilations, self).__init__(args)
    (self.compilations, ) = self.args


class CompileSetup(AnalysisElement):
  headers = ('compile setup', )

  def __init__(self, args):
    super(CompileSetup, self).__init__(args)
    (self.compile_setup, ) = self.args

class Util(object):
  num_items_re = re.compile(r'(\d+) items\n')

  @staticmethod
  def parse_num_items(lines_iter):
    """Parse a line of the form '<num> items' and returns <num> as an int."""
    line = lines_iter.next()
    matchobj = Util.num_items_re.match(line)
    if not matchobj:
      raise ParseError('Expected: "<num> items". Found: "%s"' % line)
    return int(matchobj.group(1))

  @staticmethod
  def parse_multiple_sections(lines_iter, expected_headers):
    """Parse multiple sections."""
    return [Util.parse_section(lines_iter, header) for header in expected_headers]

  @staticmethod
  def write_multiple_sections(outfile, headers, reps, inline_vals=True):
    """Write multiple sections."""
    for header, rep in zip(headers, reps):
      Util.write_section(outfile, header, rep, inline_vals)

  @staticmethod
  def parse_section(lines_iter, expected_header=None):
    """Parse a single section."""
    if expected_header:
      line = lines_iter.next()
      if expected_header + ':\n' != line:
        raise ParseError('Expected: "%s:". Found: "%s"' % (expected_header, line))
    n = Util.parse_num_items(lines_iter)
    relation = defaultdict(list)  # Values are lists, to accommodate relations.
    for i in xrange(n):
      k, _, v = lines_iter.next().partition(' -> ')
      if len(v) == 1:  # Value on its own line.
        v = lines_iter.next()
      relation[k].append(v[:-1])
    return relation

  @staticmethod
  def write_section(outfile, header, rep, inline_vals=True):
    """Write a single section.

    Itens are sorted, for ease of testing."""
    outfile.write(header + ':\n')
    items = []
    if isinstance(rep, dict):
      for k, vals in rep.iteritems():
        for v in vals:
          items.append('%s -> %s%s' % (k, '' if inline_vals else '\n', v))
    else:
      for x in rep:
        items.append(x)

    items.sort()
    outfile.write('%d items\n' % len(items))
    for item in items:
      outfile.write(item)
      outfile.write('\n')

  @staticmethod
  def split_dict(d, splits):
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

  @staticmethod
  def merge_dicts(dicts):
    """Merges multiple dicts into one.

    Assumes keys don't overlap.
    """
    ret = defaultdict(list)
    for (k, v) in itertools.chain(*[d.iteritems() for d in dicts]):
      ret[k] = v
    return ret
