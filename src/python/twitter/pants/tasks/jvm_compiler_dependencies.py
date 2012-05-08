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
import re

from collections import defaultdict

from twitter.pants import get_buildroot

class Dependencies(object):
  """
    Can map source files to class files by parsing jvm compiler dependency files with lines of the
    form:

    [source file path] -> [class file path]

    All paths are assumed to be normalized to be relative to the classfile output directory.
  """

  _CLASS_FILE_NAME_PARSER = re.compile(r'(?:\$.*)*\.class$')

  def __init__(self, outputdir, depfile):
    self.outputdir = outputdir
    self.depfile = depfile

  def findclasses(self, targets):
    """
      Returns a mapping from a target to its source to classes mapping.
      For example:

      dependencies = Dependencies(outdir, depfile)
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
    if os.path.exists(self.depfile):
      with open(self.depfile, 'r') as deps:
        for dep in deps.readlines():
          src, cls = dep.strip().split('->')
          sourcefile = os.path.relpath(os.path.join(self.outputdir, src.strip()), get_buildroot())
          if sourcefile in sources:
            classfile = os.path.relpath(os.path.join(self.outputdir, cls.strip()), self.outputdir)
            target = target_by_source[sourcefile]
            relsrc = os.path.relpath(sourcefile, target.target_base)
            classes_by_target_by_source[target][relsrc].add(classfile)
    return classes_by_target_by_source
