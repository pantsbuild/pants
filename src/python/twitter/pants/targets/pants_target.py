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

from twitter.pants.base.address import Address
from twitter.pants.base.build_manual import manual
from twitter.pants.base.parse_context import ParseContext
from twitter.pants.base.target import Target, TargetDefinitionException


@manual.builddict(tags=["anylang"])
class Pants(Target):
  """A pointer to a pants target.

  Useful, for example, in a target's dependencies list. One target can depend
  on several others; Each pants() target refers to one of those.
  """

  _DEFINITION_ERROR_MSG = ("An invalid pants pointer has been specified. "
                           "Please identify this reference and correct the issue: ")

  def __init__(self, spec, exclusives=None):
    """
    :param string spec: target address. E.g., `src/java/com/twitter/common/util/BUILD\:util`
    """
    # it's critical the spec is parsed 1st, the results are needed elsewhere in constructor flow
    parse_context = ParseContext.locate()

    def parse_address():
      if spec.startswith(':'):
        # the :[target] could be in a sibling BUILD - so parse using the canonical address
        pathish = "%s:%s" % (parse_context.buildfile.canonical_relpath, spec[1:])
        return Address.parse(parse_context.buildfile.root_dir, pathish, False)
      else:
        return Address.parse(parse_context.buildfile.root_dir, spec, False)

    try:
      self.address = parse_address()
    except IOError as e:
      self.address = parse_context.buildfile.relpath
      raise TargetDefinitionException(self, '%s%s' % (self._DEFINITION_ERROR_MSG, e))

    # We must disable the re-init check, because our funky __getattr__ breaks it.
    # We're not involved in any multiple inheritance, so it's OK to disable it here.
    super(Pants, self).__init__(self.address.target_name, reinit_check=False, exclusives=exclusives)

  def _register(self):
    # A pants target is a pointer, do not register it as an actual target (see resolve).
    pass

  def _locate(self):
    return self.address

  def resolve(self):
    # De-reference this pants pointer to an actual parsed target.
    resolved = Target.get(self.address)
    if not resolved:
      raise TargetDefinitionException(self, '%s%s' % (self._DEFINITION_ERROR_MSG, self.address))
    for dep in resolved.resolve():
      yield dep

  def get(self):
    """De-reference this pants pointer to a single target.

    If the pointer aliases more than one target a LookupError is raised.
    """
    resolved = [t for t in self.resolve() if t.is_concrete]
    if len(resolved) > 1:
      raise LookupError('%s points to more than one target: %s' % (self, resolved))
    return resolved.pop()

  def __getattr__(self, name):
    try:
      return Target.__getattribute__(self, name)
    except AttributeError as e:
      try:
        return getattr(self.get(), name)
      except (AttributeError, LookupError):
        raise e
