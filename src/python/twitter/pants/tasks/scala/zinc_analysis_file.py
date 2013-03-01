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
  def __init__(self,
               stop_after=None,
               package_prefixes=['com', 'org', 'net']):
    """
    Params:
    - stop_after: a boolean flag. If true, only part of the analysis file will be parsed.
    - package_prefixes: a list of package names that identify package roots. When translating
      class file paths to class names, these are the package names where the conversion
      will stop.
    """
    self.stop_after = stop_after
    self.package_prefixes = set(package_prefixes)

    # The analysis files we gather information from.
    self.analysis_files = []

    # Map from scala source files to the class files generated from that source
    self.products = defaultdict(set)
    # map from scala source files to the classes generated from that source.
    self.product_classes = defaultdict(set)

    # Map from scala sources to jar files or class filesthey depend on.
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
    """
    Convert a class file path referenced in an analysis file to the
    name of the class contained in it.

    In zinc relations from the analysis files, binary class dependencies 
    and compilation products are specifies as pathnames relative to the
    the build root, like ".pants.d/scalac/classes/6b94834/com/pkg/Foo.class".
    For dependency analysis, we need to convert that the name of the 
    class contained in the class file, like "com.pkg.Foo".
    """

    def _isValidPackageSegment(seg):
      # The class name from a class file will be the result of stripping out anything
      # that doesn't look like a valid packagename segment. So, for example, if there is a path 
      # segement containing a ".", that's not a valid package segment.
      # A package segment is valid if:
      # - All path segments after it are valid, and
      # - its name is a valid package identifier name in JVM code (so no "." characters,
      #    no "-" characters), and
      # - it is less than 30 characters long. (This is an ugly heuristic which appears
      #    to work, but which I'm uncomfortable with.
      # - it is not named "classes". (This is another ugly heuristic.)
      if seg.find(".") != -1 or seg.find("-") != -1 or len(seg) > 30:
        return False
      else:
        return True

    if not classfile.endswith(".class"):
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
      segments = classfile.split("/")
      segments.reverse()
      # The root name of the class is the last segment of the pathname
      # with ".class" removed.
      classname = segments[0]
      for seg in segments[1:]:
        if _isValidPackageSegment(seg):
          classname = "%s.%s" % (seg, classname)
          if seg in self.package_prefixes:
            return classname
        else:
          return classname
    # If we reach here, none of the segments were valid, so this wasn't
    # a valid classfile path.
    return None

  def add_and_parse_file(self, analysis_file, classes_dir):
    zincfile = '%s.relations' % analysis_file
    try:
      zincfile = open(zincfile, 'r')
    except IOError:
      print 'Warning: analysis file %s not found' % analysis_file_path
      return
    mode = None

    def change_mode_to(new_mode):
      if mode == self.stop_after:
        return 'done'
      else:
        return new_mode

    for line in zincfile:
      if line.startswith('products:'):
        mode = change_mode_to('products')
      elif line.startswith('binary dependencies:'):
        mode = change_mode_to('binary')
      elif line.startswith('source dependencies:'):
        mode = change_mode_to('source')
      elif line.startswith('external dependencies:'):
        mode = change_mode_to('external')
      elif line.startswith('class names:'):
        mode = change_mode_to('class')
      else:
        (src, sep, dep) = line.partition('->')
        src = src.strip()
        dep = dep.strip()
        if sep == '' and line != '\n':
            print ('Syntax error: line is neither a modeline nor a dep. "%s"'  %
                    line)
            continue
        if mode == 'products':
          self.products[src].add(dep)
          cl = self._classfile_to_classname(dep, classes_dir)
          if cl is not None:
            self.product_classes[src].add(cl)
        elif mode == 'binary':
          self.binary_deps[src].add(dep)
          cl = self._classfile_to_classname(dep, classes_dir)
          if cl is not None:
            self.binary_dep_classes[src].add(cl)
        elif mode == 'source':
          self.source_deps[src].add(dep)
        elif mode == 'external':
          self.external_deps[src].add(dep)
        elif mode == 'class':
          self.class_names[src].add(dep)
        else:
          print 'Unprocessed line, mode = %s' % mode
      if mode == 'done':
        return

