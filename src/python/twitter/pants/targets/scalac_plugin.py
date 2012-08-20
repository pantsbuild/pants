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

from twitter.pants.targets.scala_library import ScalaLibrary

class ScalacPlugin(ScalaLibrary):
  """Defines a target that produces a scalac_plugin."""

  def __init__(self, name, classname,
               plugin=None,
               sources=None,
               java_sources=None,
               provides=None,
               dependencies=None,
               excludes=None,
               resources=None):

    """
      name:         The name of this module target, addressable via pants via the portion of the
                    spec following the colon - required.
      classname:    The fully qualified plugin class name - required.
      plugin:       The name of the plugin which defaults to name if not supplied.
      sources:      A list of paths containing the scala source files this module's jar is compiled
                    from.
      java_sources: An optional list of java_library dependencies containing the java sources this
                    module's jar is in part compiled from.
      provides:     An optional Dependency object indicating the the ivy artifact to export.
      dependencies: An optional list of Dependency objects specifying the binary (jar) dependencies
                    of this module.
      excludes:     An optional list of dependency exclude patterns to filter all of this module's
                    transitive dependencies against.
      resources:    An optional list of paths containing resources to place in this module's jar.
    """

    ScalaLibrary.__init__(self, name, sources, java_sources, provides, dependencies, excludes,
                          resources)
    self.add_label('scalac_plugin')
    self.plugin = plugin or name
    self.classname = classname
