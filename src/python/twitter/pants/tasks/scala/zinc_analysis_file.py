# ==================================================================================================
# Copyright 2011 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

__author__ = 'Mark C. Chu-Carroll'

from collections import defaultdict


class ZincAnalysisCollection(object):
  """A wrapper for a collection of zinc analysis files.

  This contains the information from a collection of Zinc analysis files, merged together,
  for use in dependency analysis.
  """
  # The sections in the analysis file. Do not renumber! Code below relies on this numbering.
  PRODUCTS, BINARY, SOURCE, EXTERNAL, CLASS, DONE, UNKNOWN = range(0, 7)

  def __init__(self, stop_after=None, package_prefixes=None):
    """
    Params:
    - stop_after: If specified, parsing will stop after this section is done.
    - package_prefixes: a list of package names that identify package roots. When translating
      class file paths to class names, these are the package names where the conversion
      will stop.
    """
    self.stop_after = stop_after
    self.package_prefixes = set(package_prefixes or ['com', 'org', 'net'])

    # Map from scala source files to the class files generated from that source
    self.products = defaultdict(set)
    # map from scala source files to the classes generated from that source.
    self.product_classes = defaultdict(set)

    # Map from scala sources to jar files or class files they depend on.
    self.binary_deps = defaultdict(set)
    # Map from scala sources to classes that they depend on.
    self.binary_dep_classes = defaultdict(set)

    # Map from scala sources to the source files providing the classes that they depend on
    # The set of source files here does *not* appear to include inheritance!
    # eg, in src/jvm/com/foursquare/api/util/BUILD:util,
    # in the source file ClientMetrics, class ClientView extends PrettyEnumeration, but
    # the file declaring PrettyEnumeration is *not* in the source deps.
    # But PrettyEnumeration *is* included in the list of classes in external_deps.
    self.source_deps = defaultdict(set)

    # Map from scala sources to the classes that they depend on.
    # (Not class files but just classes.)
    self.external_deps = defaultdict(set)

    # Map from scala sources to the classes that they provide.
    # (Again, not class files, fully-qualified class names.)
    self.class_names = defaultdict(set)

  def _classfile_to_classname(self, classfile, basedir):
    """ Convert a class file referenced in an analysis file to the name of the class

    In zinc relations from the analysis files, binary class dependencies 
    and compilation products are specifies as pathnames relative to the
    the build root, like ".pants.d/scalac/classes/6b94834/com/pkg/Foo.class".
    For dependency analysis, we need to convert that the name of the 
    class contained in the class file, like "com.pkg.Foo".
    """
    if not classfile.endswith('.class'):
      return None
    # strip '.class' from the end
    classfile = classfile[:-6]
    # If it's a path relative to the known basedir, strip that off.
    if classfile.startswith(basedir):
      classfile = classfile[len(basedir):]
      return classfile.replace('/', '.')
    else:
      # Segment the path, and find the trailing segment that consists of valid
      # package elements.
      segments = classfile.split('/')
      segments.reverse()
      # The root name of the class is the last segment of the pathname
      # with ".class" removed.
      classname_parts = [segments[0]]
      for seg in segments[1:]:
        # Heuristics for detecting a valid package segment.
        if seg.find('.') == -1 and seg.find('-') == -1 and len(seg) < 30:
          classname_parts.append(seg)
          if seg in self.package_prefixes:
            return '.'.join(reversed(classname_parts))
        else:
          return '.'.join(reversed(classname_parts))
    # If we reach here, none of the segments were valid, so this wasn't
    # a valid classfile path.
    return None

  def add_and_parse_file(self, analysis_file, classes_dir):
    sections = {
      'products': ZincAnalysisCollection.PRODUCTS,
      'binary dependencies': ZincAnalysisCollection.BINARY,
      'source dependencies': ZincAnalysisCollection.SOURCE,
      'external dependencies': ZincAnalysisCollection.EXTERNAL,
      'class names': ZincAnalysisCollection.CLASS
    }

    # Note: in order of section constants above.
    depmaps = (self.products, self.binary_deps, self.source_deps, self.external_deps, self.class_names)
    classes_maps = (self.product_classes, self.binary_dep_classes, None, None, None)

    relations_file = '%s.relations' % analysis_file
    try:
      with open(relations_file, 'r') as zincfile:
        current_section = None

        for line in zincfile:
          if line.startswith('   '):
            (src, sep, dep) = line.partition(' -> ')
            src = src[3:]
            dep = dep.rstrip()
            if sep == '' and line != '\n':
                print('Syntax error: line is neither a section header nor a dep. "%s"' % line)
                continue
            depmaps[current_section][src].add(dep)
            classes_map = classes_maps[current_section]
            if classes_map is not None:
              cl = self._classfile_to_classname(dep, classes_dir)
              if cl is not None:
                classes_map[src].add(cl)
          elif line.endswith(':\n'):
            current_section = ZincAnalysisCollection.DONE if current_section == self.stop_after \
              else sections[line[0:-2]]
          if current_section == ZincAnalysisCollection.DONE:
            return
    except IOError:
      print 'ERROR: relations file %s not found' % relations_file
    except KeyError as e:
      print 'ERROR: unrecognized section: %s' % e
