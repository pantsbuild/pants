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

__author__ = 'Phil Hom'

import os

from .extract import Extract
from .ivy_resolve import IvyResolve


class IdlResolve(IvyResolve):

  # TODO(John Sirois): rework ivy_resolve to allow idl resolution without subclassing
  #   (via goal dependencies instead)
  def __init__(self, context):
    super(IdlResolve, self).__init__(context, ['idl'])

  # Carve out the custom behavior we need in the base machinery with a few overrides:
  # + don't do a classpath resolve, we only want to resolve individual idl jar closures
  # + don't generate ivy reports, let IvyResolve handle this
  # + only map idl jars: an idl dependency graph should be pure idl jars
  # + warn about idl classpaths that have non-idl jars

  def _extract_classpathdeps(self, targets):
    # IDL files don't contribute to classpaths.
    return set()

  def _generate_ivy_report(self):
    pass

  def _mapfor_typename(self):
    return 'idl_dependencies'

  def _mapto_dir(self):
    return os.path.join(self._work_dir, 'mapped-idls')

  def _map_jar(self, org, name, conf, path):
    # The spec says idl only jars should have an idl classifier and depend only on other such
    # artifacts, but in practice the spec is often not met.  It's useful to allow direct
    # registration of jars containing idl no matter the form of the jar.  We do restrict transitive
    # idl deps however to those that conform with the spec.
    is_idl = Extract.is_registered_jar(org, name) or path.endswith('-idl.jar')
    if not is_idl and super(IdlResolve, self)._map_jar(org, name, conf, path):
      self.context.log.warn('Ignoring invalid idl dependency: %s' % path)
    return is_idl

