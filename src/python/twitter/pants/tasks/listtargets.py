# =============================================================================
# Copyright 2012 Twitter, Inc.
# -----------------------------------------------------------------------------
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
# =============================================================================

from twitter.pants.base.build_environment import get_buildroot
from twitter.pants.base.build_file import BuildFile
from twitter.pants.base.target import Target

from .console_task import ConsoleTask
from .task_error import TaskError


class ListTargets(ConsoleTask):
  """
  Lists all BUILD targets in the system with no arguments, otherwise lists all
  the BUILD targets that reside in the the BUILD files hosting the specified
  targets.
  """
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    super(ListTargets, cls).setup_parser(option_group, args, mkflag)

    option_group.add_option(
        mkflag("provides"),
        action="store_true",
        dest="list_provides", default=False,
        help="Specifies only targets that provide an artifact should be "
        "listed. The output will be 2 columns in this case: "
        "[target address] [artifact id]")

    option_group.add_option(
        mkflag("provides-columns"),
        dest="list_provides_columns",
        default='address,artifact_id',
        help="Specifies the columns to include in listing output when "
        "restricting the listing to targets that provide an artifact. "
        "Available columns are: address, artifact_id, repo_name, repo_url "
        "and repo_db")

    option_group.add_option(
        mkflag("documented"),
        action="store_true",
        dest="list_documented",
        default=False,
        help="Prints only targets that are documented with a description.")

  def __init__(self, context, **kwargs):
    super(ListTargets, self).__init__(context, **kwargs)

    self._provides = context.options.list_provides
    self._provides_columns = context.options.list_provides_columns
    self._documented = context.options.list_documented
    self._root_dir = get_buildroot()

  def console_output(self, targets):
    if self._provides:
      def extract_artifact_id(target):
        provided_jar, _, _ = target.get_artifact_info()
        return "%s%s%s" % (provided_jar.org, '#', provided_jar.name)

      extractors = dict(
          address=lambda target: str(target.address),
          artifact_id=extract_artifact_id,
          repo_name=lambda target: target.provides.repo.name,
          repo_url=lambda target: target.provides.repo.url,
          repo_db=lambda target: target.provides.repo.push_db,
      )

      def print_provides(column_extractors, address):
        target = Target.get(address)
        if target.is_exported:
          return " ".join(extractor(target) for extractor in column_extractors)

      try:
        column_extractors = [extractors[col] for col in (self._provides_columns.split(','))]
      except KeyError:
        raise TaskError("Invalid columns specified %s. Valid ones include address, artifact_id, "
                        "repo_name, repo_url and repo_db." % self._provides_columns)

      print_fn = lambda address: print_provides(column_extractors, address)
    elif self._documented:
      def print_documented(address):
        target = Target.get(address)
        if target.description:
          return '%s\n  %s' % (address, '\n  '.join(target.description.strip().split('\n')))
      print_fn = print_documented
    else:
      print_fn = lambda addr: str(addr)

    visited = set()
    for address in self._addresses():
      result = print_fn(address)
      if result and result not in visited:
        visited.add(result)
        yield result

  def _addresses(self):
    if self.context.target_roots:
      for target in self.context.target_roots:
        yield target.address
    else:
      for buildfile in BuildFile.scan_buildfiles(self._root_dir):
        for address in Target.get_all_addresses(buildfile):
          yield address
