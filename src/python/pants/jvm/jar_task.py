# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from contextlib import closing, contextmanager

from pants.java.jar.jar import Jar

from .nailgun_task import NailgunTask


class JarTask(NailgunTask):
  """A baseclass for tasks that need to create or update jars.

  All subclasses will share the same underlying nailgunned jar tool and thus benefit from fast
  invocations.
  """

  _JAR_TOOL_CLASSPATH_KEY = 'jar_tool'

  def __init__(self, context, workdir):
    super(JarTask, self).__init__(context, workdir=workdir, jdk=True)

    # TODO(John Sirois): Consider poking a hole for custom jar-tool jvm args - namely for Xmx
    # control.

    jar_bootstrap_tools = Jar.tool_targets(context.config)
    self.register_jvm_tool(self._JAR_TOOL_CLASSPATH_KEY, jar_bootstrap_tools)

  @contextmanager
  def open_jar(self, path, overwrite=False, compressed=True, jar_rules=None):
    """Yields a :class:`twitter.pants.java.jar.Jar` that will be closed when the context exits.

    :param string path: the path to the jar file
    :param bool overwrite: overwrite the file at ``path`` if it exists; ``False`` by default; ie:
      update the pre-existing jar at ``path``
    :param bool compressed: entries added to the jar should be compressed; ``True`` by default
    """
    jar_tool_classpath = self.tool_classpath(self._JAR_TOOL_CLASSPATH_KEY)
    with closing(Jar(jar_tool_classpath,
                     path,
                     overwrite=overwrite,
                     compressed=compressed,
                     jar_rules=jar_rules,
                     executor=self.create_java_executor())) as jar:
      yield jar
