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

__author__ = 'John Sirois'

from . import Command

from twitter.common.collections import OrderedSet

from twitter.pants.base import Address, BuildFile, Target
from twitter.pants import is_exported

import traceback

class List(Command):
  """Lists BUILD file targets."""

  __command__ = 'list'

  def setup_parser(self, parser, args):
    parser.set_usage("%prog list ([spec]...)")
    parser.add_option("-d", "--directory", action="store_true", dest = "is_directory_list",
                      default = False, help = """Specifies specs should be treated as plain paths,
                      in which case all targets found in all BUILD files under the paths will be
                      listed.""")
    parser.add_option("--provides", action="store_true", dest = "only_provides", default = False,
                      help = "Specifies only targets that provide an artifact should be listed. "
                             "The output will be 2 columns in this case: "
                             "[target address] [artifact id]")
    parser.add_option("--provides-columns", dest = "provides_columns",
                      default = 'address,artifact_id',
                      help = "Specifies the columns to include in listing output when restricting "
                             "the listing to targets that provide an artifact.  Available columns "
                             "are: address, artifact_id, repo_name, repo_url, repo_db")
    parser.add_option("-s", "--separator", dest = "separator", default = "#",
                      help = "Specifies the separator to use between the org/name/rev components "
                             "of a dependency's fully qualified name.  Only makes sense when "
                             "combined with --provides")
    parser.add_option("--documented", dest = "documented", default = False, action="store_true",
                      help = "Prints only targets with documentation")
    parser.epilog = """Lists all BUILD targets in the system with no arguments, otherwise lists all
    the BUILD targets that reside in the the BUILD files hosting the specified targets."""

  def __init__(self, root_dir, parser, argv):
    Command.__init__(self, root_dir, parser, argv)

    self.buildfiles = self._parse_buildfiles() if self.args else BuildFile.scan_buildfiles(root_dir)

  def _parse_buildfiles(self):
    buildfiles = OrderedSet()
    for spec in self.args:
      try:
        if self.options.is_directory_list:
          for buildfile in BuildFile.scan_buildfiles(self.root_dir, spec):
            buildfiles.add(buildfile)
        else:
          buildfiles.add(Address.parse(self.root_dir, spec).buildfile)
      except:
        self.error("Problem parsing spec %s: %s" % (spec, traceback.format_exc()))
    return buildfiles

  def execute(self):
    if self.options.only_provides:
      def extract_artifact_id(target):
        provided_jar = target._as_jar_dependency()
        return "%s%s%s" % (provided_jar.org, self.options.separator, provided_jar.name)

      extractors = dict(
        address = lambda target: str(target.address),
        artifact_id = extract_artifact_id,
        repo_name = lambda target: target.provides.repo.name,
        repo_url = lambda target: target.provides.repo.url,
        repo_db = lambda target: target.provides.repo.push_db,
      )

      column_extractors = [ extractors[col] for col in (self.options.provides_columns.split(',')) ]
      print_fn = lambda address: self._print_provides(column_extractors, address)
    elif self.options.documented:
      def print_documented(address):
        target = Target.get(address)
        if target.description:
          return '%s\n  %s' % (address, '\n  '.join(target.description.strip().split('\n')))
      print_fn = print_documented
    else:
      print_fn = lambda address: str(address)

    for buildfile in self.buildfiles:
      for address in Target.get_all_addresses(buildfile):
        line = print_fn(address)
        if line:
          print line

  def _print_provides(self, column_extractors, address):
    target = Target.get(address)
    if is_exported(target):
      return " ".join(extractor(target) for extractor in column_extractors)

