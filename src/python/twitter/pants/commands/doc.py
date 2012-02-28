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

from __future__ import print_function

__author__ = 'John Sirois'

from . import Command

import json
import os
import shutil
import subprocess
import traceback
import pkg_resources
from copy import copy
from datetime import datetime

from twitter.common.collections import OrderedSet
from twitter.common.config import Properties
from twitter.pants import is_exported, is_jvm, is_doc
from twitter.pants.base import Address, Target
from twitter.pants.targets import JavaLibrary
from twitter.pants.ant import AntBuilder
from twitter.pants.pants_doc import DocBuilder

_ASSETS_DIR = 'doc/assets'

class Doc(Command):
  """Generates documentation for a set of targets."""

  __command__ = 'doc'

  @staticmethod
  def _is_documentable(target):
    # TODO(John Sirois): support java_thrift_library, java_protobuf_library, pydoc and scaladoc
    return isinstance(target, JavaLibrary) or is_doc(target)

  def setup_parser(self, parser, args):
    parser.set_usage("%prog doc ([spec]...)")
    parser.add_option("--provides", action="store_true", dest = "only_provides", default = False,
                      help = "Specifies docs should only be generated for build targets with "
                             "a provides artifact")
    parser.add_option("--ignore-failure", action="store_true", dest = "ignore_failure",
                      default = False,
                      help = "Specifies that javadoc failures should not be reflected in this "
                             "command's exit code.")
    parser.add_option("--link-changelog", action="store_true", dest = "link_changelog",
                      default = False,
                      help = "Causes a link to the artifact's changelog to be shown in the "
                             "artifact header")
    parser.add_option("--title", dest = "title", default = "API Javadoc",
                      help = "Specifies a custom title for the generated javadoc site.")
    parser.epilog = """Generates documentation for the specified targets or else all documentable
    targets if none are specified.  If any of the specified targets are not documentable, aborts
    with a non-zero exit code"""

  def __init__(self, root_dir, parser, argv, target_path = None):
    Command.__init__(self, root_dir, parser, argv)

    self.only_provides = self.options.only_provides
    self.link_changelog = self.options.link_changelog

    if self.args:
      self.targets = self._parse_targets(root_dir)
    else:
      def get_targets():
        for address in Command.scan_addresses(root_dir):
          target = Target.get(address)
          if Doc._is_documentable(target):
            yield target
      self.targets = list(get_targets())

    if target_path:
      self.target_path = target_path
    else:
      self.target_path = os.path.join(root_dir, 'target', 'pants.doc')
    self.java_src_prefix = os.path.join(root_dir, 'src', 'java')
    self.ivy_jar = os.path.join(root_dir, 'build-support', 'ivy', 'lib', 'ivy-2.2.0.jar')
    self.ivy_settings = os.path.join(root_dir, 'build-support', 'ivy', 'ivysettings.xml')

  def _artifact_data_path(self, base):
    return os.path.abspath(os.path.join(base, 'artifacts.js'))

  def _parse_targets(self, root_dir):
    targets = OrderedSet()
    for spec in self.args:
      try:
        address = Address.parse(root_dir, spec)
      except:
        self.error("Problem parsing spec %s: %s" % (spec, traceback.format_exc()))

      try:
        target = Target.get(address)
      except:
        self.error("Problem parsing target %s: %s" % (address, traceback.format_exc()))

      if not Doc._is_documentable(target):
        self.error("Target: %s is not documentable" % address)

      targets.add(target)

    return targets

  @staticmethod
  def _walk_assets(directory):
    assets = pkg_resources.resource_listdir(__name__, directory)
    files, dirs = [], []
    for f in assets:
      if pkg_resources.resource_isdir(__name__, os.path.join(directory, f)):
        dirs.append(f)
      else:
        files.append(f)
    yield directory, dirs, files
    for dir in dirs:
      for r, d, f in Doc._walk_assets(os.path.join(directory, dir)):
        yield r, d, f

  def execute(self):
    if os.path.exists(self.target_path):
      shutil.rmtree(self.target_path)

    # we pass self.targets and self.target_path as initial values here.
    # during recursive execution (in the case of dependencies on doc targets)
    # these are called with different targets/target/path values
    if self.execute_javadoc(self.targets, self.target_path):
      print("JavaDoc execution failed")
      return 1
    if self.execute_pantsdoc(self.targets, self.target_path):
      print("PantsDoc execution failed")
      return 1
    return 0

  def execute_javadoc(self, targets, target_path):
    if not os.path.exists(target_path):
      os.makedirs(target_path)

    all_sources, all_deps = self._extract_java_sources_and_deps(targets)
    if all_sources == []:
      return 0

    doc_target = self._create_doc_target(targets, all_sources, all_deps)
    classpath_result, classpath_file = self._create_classpath_file(doc_target, target_path)
    if classpath_result != 0:
      print("Failed to generate javadoc classpath.")
      return classpath_result

    self._create_artifact_data(targets, target_path)
    sources_file = self._create_sources_file(doc_target, target_path)
    command = [
      'javadoc',
      '-encoding', 'UTF-8',
      '-notimestamp',
      '-doctitle', self.options.title,
      '-use',
      '-linksource',
      '-top', '<script type="text/javascript">top.updateArtifact(window.location);</script>',
      '-classpath', '@%s' % classpath_file,
      '-d', target_path,
      '@%s' % sources_file
    ]

    # Propagate JVM flags via ANT_OPTS
    if 'ANT_OPTS' in os.environ:
      for ant_opt in os.environ['ANT_OPTS'].split():
        command += [ '-J%s' % ant_opt.strip() ]

    # Always provide external linking for java API
    offlinelinks = set([ 'http://download.oracle.com/javase/6/docs/api/' ])

    def link(target):
      for jar in target.jar_dependencies:
        if jar.apidocs:
          offlinelinks.add(jar.apidocs)
    doc_target.walk(link, is_jvm)

    for link in offlinelinks:
      command.extend(['-linkoffline', link, link])

    javadoc_result = subprocess.call(command)

    if self.options.ignore_failure or javadoc_result == 0:
      for root, _, files in self._walk_assets(_ASSETS_DIR):
        newdir = os.path.join(target_path, os.path.relpath(root, _ASSETS_DIR))
        if not os.path.exists(newdir):
          os.makedirs(newdir)
        for filename in files:
          if not filename.startswith("javadoc"):
            with open(os.path.join(newdir, filename), 'w') as output:
              output.write(pkg_resources.resource_string(__name__, os.path.join(root, filename)))

      # figure out if we docd multiple packages
      docd_packages = OrderedSet()
      for source in doc_target.sources:
        docd_packages.add(os.path.dirname(source))

      # write javadoc.html, special casing for single package doc targets
      new_file = os.path.join(target_path, "javadoc.html")
      if len(docd_packages) > 1:
        source_file = "javadoc.html"
      else:
        source_file = "javadoc-single-package.html"
      with open(new_file, 'w') as output:
        output.write(pkg_resources.resource_string(__name__,
          os.path.join(_ASSETS_DIR, source_file)))
      return 0
    return javadoc_result

  def _extract_java_sources_and_deps(self, targets):
    all_sources = []
    all_deps = OrderedSet()
    for target in targets:
      if (not self.only_provides or is_exported(target)) and (not is_doc(target)):
        for source in target.sources:
          source_path = os.path.join(self.java_src_prefix, source)
          if os.path.exists(source_path):
            all_sources.append(source_path)
          else:
            print("skipping %s" % source_path)

          for jar_dep in target.jar_dependencies:
            if jar_dep.rev:
              all_deps.add(copy(jar_dep).intransitive())
    return all_sources, all_deps

  def _create_doc_target(self, targets, all_sources, all_deps):
    def create_meta_target():
      return JavaLibrary('pants.doc.deps',
                         all_sources,
                         dependencies = all_deps,
                         is_meta = True)

    # TODO(John Sirois): Find a better way to do_in_context when we don't care about the context
    return list(targets)[0].do_in_context(create_meta_target)

  def _create_classpath_file(self, target, target_path):
    classpath_file = os.path.abspath(os.path.join(target_path, 'classpath.txt'))
    classpath_result = subprocess.call([
      'java',
      '-jar', self.ivy_jar,
      '-warn',
      '-settings', self.ivy_settings,
      '-ivy', self._create_ivy_file(target, target_path),
      '-cachepath', classpath_file,
    ])
    return classpath_result, classpath_file

  def _create_ivy_file(self, target, target_path):
    ivy_file = os.path.abspath(os.path.join(target_path, 'ivy.xml'))
    AntBuilder.generate_ivy(self.root_dir, ivy_file, target)
    return ivy_file

  def _create_artifact_data(self, targets, target_path):
    props_by_repo = {}
    def get_publish_properties(target):
      if target.provides.repo not in props_by_repo:
        with open(target.provides.repo.push_db) as props:
          props_by_repo[target.provides.repo] = Properties.load(props)
      return props_by_repo.get(target.provides.repo)

    data = {}
    for target in targets:
      if is_exported(target):
        props = get_publish_properties(target)
        for source in target.sources:
          source_path = os.path.join(self.java_src_prefix, source)
          key = '%s%%%s' % (target.provides.org, target.provides.name)
          if os.path.exists(source_path):
            if 'revision.major.%s' % key in props:
              major = props['revision.major.%s' % key]
              minor = props['revision.minor.%s' % key]
              patch = props['revision.patch.%s' % key]
              revision = '%s.%s.%s' % (major, minor, patch)
            else:
              revision = 'NOT-PUBLISHED-YET'

            data[source] = dict(org = target.provides.org,
                                name = target.provides.name,
                                rev = revision,
                                artifactBaseUrl = target.provides.repo.url)

    with open(self._artifact_data_path(target_path), mode = 'w') as data_file:
      print("var artifacts = %s;" % json.dumps(data, sort_keys = True, indent = 2), file=data_file)
      print("artifacts.title = '%s';" % self.options.title, file=data_file)
      print("artifacts.publishDate = '%s';" % (
        datetime.now().strftime('%m/%d/%Y %I:%M %p')
      ), file=data_file)
      print("artifacts.hasChangelog = %s;" % (
        'true' if self.link_changelog else 'false'
      ), file=data_file)

  def _create_sources_file(self, target, target_path):
    sources_file = os.path.abspath(os.path.join(target_path, 'sources.txt'))
    with open(sources_file, 'w') as argfile:
      argfile.writelines(['%s\n' % s for s in target.sources])
    return sources_file

  def execute_pantsdoc(self, targets, target_path):
    if not os.path.exists(target_path):
      os.makedirs(target_path)

    try:
      doc_targets = filter(is_doc, targets)
      for doc_target in doc_targets:
        def exec_doc(dependency):
          for dep_target in dependency.resolve():
            # TODO: document how doc projects get nested
            # in pants_doc output
            if is_jvm(dep_target):
              self.execute_javadoc([dep_target],
                                   os.path.join(target_path, doc_target.id, dep_target.id))
            if is_doc(dep_target) and not dep_target in targets:
              self.execute_pantsdoc([dep_target],
                                    os.path.join(target_path, doc_target.id, dep_target.id))
        doc_target.walk(exec_doc)

      executor = DocBuilder(target_path)
      return executor.build(doc_targets, self.args)
    except:
      self.error("Problem executing PantsDocBuilder for targets %s: %s" % (doc_targets,
                                                                           traceback.format_exc()))
