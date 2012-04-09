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

from twitter.common.collections.ordereddict import OrderedDict
from twitter.common.collections.orderedset import OrderedSet

from twitter.pants import is_internal
from twitter.pants.targets.jvm_binary import JvmBinary
from twitter.pants.tasks import Task


class JvmBinaryTask(Task):

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag("outdir"), dest="jvm_binary_create_outdir",
                            help="Create bundles and archives in this directory.")

    option_group.add_option(mkflag("deployjar"), mkflag("deployjar", negate=True),
                            dest="jvm_binary_create_deployjar", default=False,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Create a monolithic deploy jar containing this "
                                 "binaries classfiles as well as all classfiles it depends on "
                                 "transitively.")

  def __init__(self, context):
    Task.__init__(self, context)

  def is_binary(self, target):
    return isinstance(target, JvmBinary)

  def require_jar_dependencies(self, predicate=None):
    self.context.products.require('jar_dependencies', predicate=predicate or self.is_binary)

  def list_jar_dependencies(self, binary, confs=None):
    jardepmap = self.context.products.get('jar_dependencies') or {}

    if confs:
      return self._mapped_dependencies(jardepmap, binary, confs)
    else:
      return self._unexcluded_dependencies(jardepmap, binary)

  def _mapped_dependencies(self, jardepmap, binary, confs):
    # TODO(John Sirois): rework product mapping towards well known types

    # Generate a map of jars for each unique artifact (org, name)
    externaljars = OrderedDict()
    visited = set()
    for conf in confs:
      mapped = jardepmap.get((binary, conf))
      if mapped:
        for basedir, jars in mapped.items():
          for externaljar in jars:
            if (basedir, externaljar) not in visited:
              visited.add((basedir, externaljar))
              keys = jardepmap.keys_for(basedir, externaljar)
              for key in keys:
                if isinstance(key, tuple) and len(key) == 3:
                  org, name, configuration = key
                  classpath_entry = externaljars.get((org, name))
                  if not classpath_entry:
                    classpath_entry = {}
                    externaljars[(org, name)] = classpath_entry
                  classpath_entry[conf] = os.path.join(basedir, externaljar)
    return externaljars.values()

  def _unexcluded_dependencies(self, jardepmap, binary):
    # TODO(John Sirois): Kill this and move jar exclusion to use confs
    excludes = set()
    for exclude_key in ((e.org, e.name) if e.name else e.org for e in binary.deploy_excludes):
      exclude = jardepmap.get(exclude_key)
      if exclude:
        for basedir, jars in exclude.items():
          for jar in jars:
            excludes.add((basedir, jar))
    self.context.log.debug('Calculated excludes:\n\t%s' % '\n\t'.join(str(e) for e in excludes))

    externaljars = OrderedSet()
    def add_jars(target):
      mapped = jardepmap.get(target)
      if mapped:
        for basedir, jars in mapped.items():
          for externaljar in jars:
            if (basedir, externaljar) not in excludes:
              externaljars.add((basedir, externaljar))
            else:
              self.context.log.debug('Excluding %s from binary' % externaljar)

    binary.walk(add_jars, is_internal)
    return externaljars
