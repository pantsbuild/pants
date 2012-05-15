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

from collections import namedtuple, defaultdict
import os
import xml

from twitter.common.collections import OrderedSet


IvyModuleRef = namedtuple('IvyModuleRef', ['org', 'name', 'rev', 'conf'])
IvyArtifact = namedtuple('IvyArtifact', ['path'])
IvyModule = namedtuple('IvyModule', ['ref', 'artifacts', 'callers'])


class IvyInfo(object):
  def __init__(self):
    self.modules_by_ref = {}  # Map from ref to referenced module.
    self.deps_by_caller = defaultdict(OrderedSet)  # Map from ref of caller to refs of modules required by that caller.

  def add_module(self, module):
    self.modules_by_ref[module.ref] = module
    for caller in module.callers:
      self.deps_by_caller[caller].add(module.ref)


class IvyUtils(object):
  """Useful methods related to interaction with ivy."""
  def __init__(self, context, cachedir):
    self._context = context
    self._cachedir = cachedir

  def identify(self):
    if len(self._context.target_roots) == 1:
      target = self._context.target_roots[0]
      if hasattr(target, 'provides') and target.provides:
        return target.provides.org, target.provides.name
      else:
        return 'internal', target.id
    else:
      return 'internal', self._context.id

  def xml_report_path(self, conf):
    """The path to the xml report ivy creates after a retrieve."""
    org, name = self.identify()
    return os.path.join(self._cachedir, '%s-%s-%s.xml' % (org, name, conf))

  def parse_xml_report(self, conf):
    """Returns the IvyInfo representing the info in the xml report."""
    ret = IvyInfo()
    etree = xml.etree.ElementTree.parse(self.xml_report_path(conf))
    doc = etree.getroot()
    for module in doc.findall('dependencies/module'):
      org = module.get('organisation')
      name = module.get('name')
      for revision in module.findall('revision'):
        rev = revision.get('name')
        confs = self._split_conf(revision.get('conf'))
        artifacts = []
        for artifact in revision.findall('artifacts/artifact'):
          artifacts.append(IvyArtifact(artifact.get('location')))
        callers = []
        for caller in revision.findall('caller'):
          for caller_conf in self._split_conf(caller.get('conf')):
            callers.append(IvyModuleRef(caller.get('organisation'), caller.get('name'),
              caller.get('callerrev'), caller_conf))
        for conf in confs:
          ret.add_module(IvyModule(IvyModuleRef(org, name, rev, conf), artifacts, callers))
    return ret

  def _split_conf(self, conf):
    return [c.strip() for c in conf.split(',')]
