# ==================================================================================================
# Copyright 2012 Twitter, Inc.
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

__author__ = 'John Sirois'

import os

from collections import defaultdict

from twitter.pants import get_buildroot
from twitter.pants.tasks import TaskError


class Dependencies(object):
  """
    Can map source files to class files by parsing jvm compiler dependency files with lines of the
    form:

    [source file path] -> [class file path]

    All paths are assumed to be normalized to be relative to the classfile output directory.
    Depfiles are written either by instances of this class or directly by compilers, such as
    jmake and zinc.
  """
  def __init__(self, outputdir):
    self.outputdir = outputdir
    self.classes_by_source = defaultdict(set)
    self.buildroot = get_buildroot()

  def load(self, depfile):
    """Load an existing depfile into this object. Any existing mappings are discarded."""
    self.classes_by_source = defaultdict(set)
    if os.path.exists(depfile):
      with open(depfile, 'r') as deps:
        for dep in deps.readlines():
          src, cls = dep.strip().split('->')
          sourcefile = os.path.relpath(os.path.join(self.outputdir, src.strip()), self.buildroot)
          classfile = os.path.relpath(os.path.join(self.outputdir, cls.strip()), self.outputdir)
          self.classes_by_source[sourcefile].add(classfile)
    else:
      raise TaskError('No depfile at %s' % depfile)

  def save(self, depfile):
    """Save this object to a depfile. Any existing mappings in the file are overwitten."""
    with open(depfile, 'w') as deps:
      for sourcefile, classfiles in self.classes_by_source.items():
        src = os.path.relpath(os.path.join(self.buildroot, sourcefile), self.outputdir)
        for cls in classfiles:
          deps.write(src)
          deps.write(' -> ')
          deps.write(cls)
          deps.write('\n')

  def add(self, sourcefile, classfiles):
    """Add a mapping to this object.

    sourcefile is assumed to be relative to the build root (note: unlike in depfiles).
    classfiles are assumed to be relative to the output directory.
    """
    self.classes_by_source[sourcefile].update(classfiles)

  def merge(self, other_deps):
    """
    Merges the other deps into this object. The other deps will take precedence. In other words, if the other
    deps provide any mapping for a source file, all that source file's existing mappings will be dropped.
    """
    for sourcefile, classfiles in other_deps.classes_by_source.items():
      self.classes_by_source[sourcefile] = classfiles.copy()

  def findclasses(self, targets):
    """
      Returns a mapping from a target to its source to classes mapping.
      For example:

      dependencies = Dependencies(outdir)
      dependencies.load(depfile)
      mapping = dependencies.findclasses(targets)
      for target, src_to_classes in mapping.items():
        for source, classes in src_to_classes.items():
          print('source: %s produces classes: %s' % (
            os.path.join(target.target_base, source),
            [os.path.join(outdir, cls) for cls in classes]
          ))
    """
    sources = set()
    target_by_source = dict()
    for target in targets:
      for source in target.sources:
        src = os.path.normpath(os.path.join(target.target_base, source))
        target_by_source[src] = target
        sources.add(src)

    classes_by_target_by_source = defaultdict(lambda: defaultdict(set))
    for sourcefile, classfiles in self.classes_by_source.items():
      if sourcefile in sources:
        target = target_by_source[sourcefile]
        relsrc = os.path.relpath(sourcefile, target.target_base)
        classes_by_target_by_source[target][relsrc] = classfiles
    return classes_by_target_by_source

