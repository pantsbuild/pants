import os
import re

from twitter.pants.binary_util import select_binary


INCLUDE_PARSER = re.compile(r'^\s*include\s+"([^"]+)"\s*$')


def find_includes(basedirs, source, log=None):
  """Finds all thrift files included by the given thrift source.

  :basedirs: A set of thrift source file base directories to look for includes in.
  :source: The thrift source file to scan for includes.
  :log: An optional logger
  """

  all_basedirs = [os.path.dirname(source)]
  all_basedirs.extend(basedirs)

  includes = set()
  with open(source, 'r') as thrift:
    for line in thrift.readlines():
      match = INCLUDE_PARSER.match(line)
      if match:
        capture = match.group(1)
        for basedir in all_basedirs:
          include = os.path.join(basedir, capture)
          if os.path.exists(include):
            if log:
              log.debug('%s has include %s' % (source, include))
            includes.add(include)
  return includes


def find_root_thrifts(basedirs, sources, log=None):
  """Finds the root thrift files in the graph formed by sources and their recursive includes.

  :basedirs: A set of thrift source file base directories to look for includes in.
  :sources: Seed thrift files to examine.
  :log: An optional logger.
  """

  root_sources = set(sources)
  for source in sources:
    root_sources.difference_update(find_includes(basedirs, source, log=log))
  return root_sources


def calculate_compile_sources_HACK_FOR_SCROOGE_LEGACY(targets, is_thrift_target):
  """Calculates the set of thrift source files that need to be compiled
  as well as their associated import/include directories.
  It does not exclude sources that are included in other sources.

  A tuple of (include dirs, thrift sources) is returned.

  :targets: The targets to examine.
  :is_thrift_target: A predicate to pick out thrift targets for consideration in the analysis.
  """

  dirs = set()
  sources = set()
  def collect_sources(target):
    for source in target.sources:
      dirs.add(os.path.normpath(os.path.join(target.target_base, os.path.dirname(source))))
      sources.add(os.path.join(target.target_base, source))
  for target in targets:
    target.walk(collect_sources, predicate=is_thrift_target)

  # This chunk of code is optional, but it might help find bugs because scrooge
  # found the wrong file and used it.
  thrift_file_to_import_paths = defaultdict(set)
  for import_path in dirs:
    for thrift_file in map(lambda p: os.path.basename(p), glob.glob('%s/*.thrift' % import_path)):
      thrift_file_to_import_paths[thrift_file].add(import_path)
    for thrift_file, import_paths in thrift_file_to_import_paths.items():
      if len(import_paths) > 1:
        self.context.log.warning("'%s' found in multiple import-paths: [%s]" % (
            thrift_file, ', '.join(import_paths)))

  return dirs, sources


def calculate_compile_sources(targets, is_thrift_target):
  """Calculates the set of thrift source files that need to be compiled.
  It does not exclude sources that are included in other sources.

  A tuple of (include basedirs, thrift sources) is returned.

  :targets: The targets to examine.
  :is_thrift_target: A predicate to pick out thrift targets for consideration in the analysis.
  """

  basedirs = set()
  sources = set()
  def collect_sources(target):
    basedirs.add(target.target_base)
    sources.update(target.sources_relative_to_buildroot())
  for target in targets:
    target.walk(collect_sources, predicate=is_thrift_target)
  return basedirs, sources


def calculate_compile_roots(targets, is_thrift_target):
  """Calculates the minimal set of thrift source files that need to be compiled.

  A tuple of (include basedirs, root thrift sources) is returned.

  :targets: The targets to examine.
  :is_thrift_target: A predicate to pick out thrift targets for consideration in the analysis.
  """

  basedirs, sources = calculate_compile_sources(targets, is_thrift_target)
  sources = find_root_thrifts(basedirs, sources)
  return basedirs, sources


def select_thrift_binary(config, version=None):
  """Selects a thrift compiler binary matching the current os and architecture.

  By default uses the repo default thrift compiler version specified in the pants config.

  config: The pants config containing thrift thrift binary selection data.
  version: An optional thrift compiler binary version override.
  """
  thrift_supportdir = config.get('thrift-gen', 'supportdir')
  thrift_version = version or config.get('thrift-gen', 'version')
  return select_binary(thrift_supportdir, thrift_version, 'thrift', config)
