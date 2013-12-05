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

import os

from twitter.pants.targets import JavaLibrary, JavaTests
from twitter.pants.tasks.jvmdoc_gen import Jvmdoc, JvmdocGen


def is_java(target):
  return isinstance(target, JavaLibrary) or isinstance(target, JavaTests)

javadoc = Jvmdoc(tool_name='javadoc')


class JavadocGen(JvmdocGen):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    cls.generate_setup_parser(option_group, args, mkflag, javadoc)

  def __init__(self, context, output_dir=None, confs=None):
    super(JavadocGen, self).__init__(context, javadoc, output_dir, confs)

  def execute(self, targets):
    self.generate_execute(targets, is_java, create_javadoc_command)


def create_javadoc_command(classpath, gendir, *targets):
  sources = []
  for target in targets:
    sources.extend(os.path.join(target.target_base, source) for source in target.sources)

  if not sources:
    return None

  # TODO(John Sirois): try com.sun.tools.javadoc.Main via ng
  command = [
    'javadoc',
    '-quiet',
    '-encoding', 'UTF-8',
    '-notimestamp',
    '-use',
    '-classpath', ':'.join(classpath),
    '-d', gendir,
  ]

  # Always provide external linking for java API
  offlinelinks = set(['http://download.oracle.com/javase/6/docs/api/'])

  def link(target):
    for jar in target.jar_dependencies:
      if jar.apidocs:
        offlinelinks.add(jar.apidocs)
  for target in targets:
    target.walk(link, lambda t: t.is_jvm)

  for link in offlinelinks:
    command.extend(['-linkoffline', link, link])

  command.extend(sources)
  return command
