from collections import defaultdict
import json
import re
import itertools
from twitter.pants import TaskError


class ParseError(TaskError):
  pass

# Classes to encapsulate various parts of the analysis. Note that data in these classes is still
# just text, possibly split on lines or '->'.


class AnalysisElement(object):
  headers = ()  # Override in subclasses.

  @classmethod
  def parse(cls, lines_iter):
    return cls(Util.parse_multiple_repeated(lines_iter, cls.headers))

  @classmethod
  def from_json_obj(cls, obj):
    return cls([obj[header] for header in cls.headers])

  def __init__(self, args):
    self.args = args
    # Subclasses can alias the elements of self.args conveniently in their own __init__.

  def write(self, outfile, inline_vals=True):
    Util.write_multiple_repeated(outfile, self.headers, self.args, inline_vals)


class AnalysisJSONEncoder(json.JSONEncoder):
  def default(self, obj):
    if isinstance(obj, AnalysisElement):
      ret = {}
      for h, a in zip(obj.__class__.headers, obj.args):
        ret[h] = a
      return ret
    else:
      super(AnalysisJSONEncoder, self).default(obj)


class Analysis(object):
  @staticmethod
  def parse_from_path(infile_path):
    with open(infile_path, 'r') as infile:
      return Analysis.parse(infile)

  @staticmethod
  def parse_json_from_path(infile_path):
    with open(infile_path, 'r') as infile:
      return Analysis.parse_json(infile)

  @staticmethod
  def parse(infile):
    lines_iter = iter(infile.read().splitlines())
    version_line = lines_iter.next()
    if version_line != 'format version: 1':
      raise Exception('Unrecognized format line: ' + version_line)
    relations = Relations.parse(lines_iter)
    stamps = Stamps.parse(lines_iter)
    apis = APIs.parse(lines_iter)
    source_infos = SourceInfos.parse(lines_iter)
    compilations = Compilations.parse(lines_iter)
    compile_setup = CompileSetup.parse(lines_iter)
    return Analysis(relations, stamps, apis, source_infos, compilations, compile_setup)

  @staticmethod
  def parse_json(infile):
    obj = json.load(infile)
    relations = Relations.from_json_obj(obj['relations'])
    stamps = Stamps.from_json_obj(obj['stamps'])
    apis = APIs.from_json_obj(obj['apis'])
    source_infos = SourceInfos.from_json_obj(obj['source infos'])
    compilations = Compilations.from_json_obj(obj['compilations'])
    compile_setup = Compilations.from_json_obj(obj['compile setup'])
    return Analysis(relations, stamps, apis, source_infos, compilations, compile_setup)

  @staticmethod
  def rebase(input_analysis_path, output_analysis_path, rebasings):
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
    analysis = Analysis.parse(analysis_path)
    splits = [x[0] for x in split_path_pairs]
    split_analyses = analysis.split(splits, catchall_path is not None)
    output_paths = [x[1] for x in split_path_pairs]
    if catchall_path is not None:
      output_paths.append(catchall_path)
    for analysis, path in zip(split_analyses, output_paths):
      analysis.write_to_path(path)

  @staticmethod
  def merge_from_paths(analysis_paths, merged_analysis_path):
    analyses = [Analysis.parse_from_path(path) for path in analysis_paths]
    merged_analysis = Analysis.merge(analyses)
    merged_analysis.write_to_path(merged_analysis_path)

  @staticmethod
  def merge(analyses):
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
          vfile = class_to_source[v]
          if vfile in src_prod:
            internal[k].append(vfile)
          else:
            external[k].append(v)
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
        internal_apis[kfile] = vs
      else:
        external_apis[k] = vs
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
    outfile.write('format version: 1\n')
    self.relations.write(outfile)
    self.stamps.write(outfile)
    self.apis.write(outfile, inline_vals=False)
    self.source_infos.write(outfile, inline_vals=False)
    self.compilations.write(outfile, inline_vals=False)
    self.compile_setup.write(outfile, inline_vals=False)

  def write_json(self, outfile):
    obj = dict(zip(('relations', 'stamps', 'apis', 'compilations'),
                   (self.relations, self.stamps, self.apis, self.compilations)))
    json.dump(obj, outfile, cls=AnalysisJSONEncoder, sort_keys=True, indent=2)

  def split(self, splits, catchall=False):
    """Split the analysis according to splits, which is a list of K iterables of source files.

    If catchall is False, returns a list of K Analysis objects, one for each of the splits, in order.
    If catchall is True, returns K+1 Analysis objects, the last one containing the analysis for any
    remainder sources not mentioned in the K splits.
    """
    splits = [set(x) for x in splits]
    if catchall:
      # Even empty sources with no products have stamps.
      all_sources = (set(itertools.chain(*[self.stamps.sources.iterkeys()]))).difference(*splits)
      splits.append(all_sources)  # The catch-all

    # Split relations.
    src_prod_splits = Util.split_dict(self.relations.src_prod, splits)
    binary_dep_splits = Util.split_dict(self.relations.binary_dep, splits)
    classes_splits = Util.split_dict(self.relations.classes, splits)

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
              internal[k].append(v)
            else:
              external[k].append(representatives[v])
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
          internal_apis[k] = vs
        else:
          external_apis[representatives[k]] = vs
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
  header_re = re.compile(r'(\d+) items')

  @staticmethod
  def parse_multiple_repeated(lines_iter, expected_headers):
    return [Util.parse_repeated(lines_iter, header) for header in expected_headers]

  @staticmethod
  def write_multiple_repeated(outfile, headers, reps, inline_vals=True):
    for header, rep in zip(headers, reps):
      Util.write_repeated(outfile, header, rep, inline_vals)

  @staticmethod
  def parse_repeated(lines_iter, expected_header):
    line = lines_iter.next()
    if expected_header + ':' != line:
      raise ParseError('Expected: "%s:". Found: "%s"' % (expected_header, line))
    line = lines_iter.next()
    matchobj = Util.header_re.match(line)
    if not matchobj:
      raise ParseError('Expected: "<num> items". Found: "%s"' % line)
    n = int(matchobj.group(1))
    relation = defaultdict(list)  # Values are lists, to accommodate relations.
    for i in xrange(n):
      k, _, v = lines_iter.next().partition(' -> ')
      if len(v) == 0:  # Value on its own line.
        v = lines_iter.next()
      relation[k].append(v)
    return relation

  @staticmethod
  def write_repeated(outfile, header, rep, inline_vals=True):
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
    ret = defaultdict(list)
    for (k, v) in itertools.chain(*[d.iteritems() for d in dicts]):
      ret[k] = v
    return ret
