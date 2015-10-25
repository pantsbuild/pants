# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.tasks.jar_task import JarTask
from pants.util.dirutil import safe_mkdir


##
## See `Appendix A` in the 'publish' documentation:
##
##    http://pantsbuild.github.io/publish.html
##
## for tips on how to adapt this example task for your own custom publishing needs.
##
class ExtraTestJarExample(JarTask):
  """Example of a pants publish plugin.

  For every JarLibrary target in the build graph, this plugin will create an 'example.txt' file,
  which will be placed in an additional jar. During publishing, this additional jar will be published
  along with the target.
  """

  def __init__(self, context, workdir):
    # Constructor for custom task. Setup things that you need at pants initialization time.
    super(ExtraTestJarExample, self).__init__(context, workdir)

  # This method is called by pants, when the RoundEngine gets to the phase where your task is
  # attached.
  def execute(self):
    # Ensure that we have a work directory to create a temporary jar.
    safe_mkdir(self.workdir)

    # For each node in the graph that was selected below, create a jar, and store a reference to
    # the jar in the product map.
    def process(target):
      self.context.log.info("Processing target %s" % target)
      jar_name = "%s.%s-extra_example.jar" % (target.provides.org, target.provides.name)
      # This is the path in .pants.d to write our new additional jar to. Note that we won't publish
      # directly from this location.
      jar_path = os.path.join(self.workdir, jar_name)

      # A sample file to stuff into the jar.
      example_file_name = os.path.join(self.workdir, "example.txt")
      with open(example_file_name, 'wb') as f:
        f.write("This is an example test file.\n")

      # Create a jar file to be published along with other artifacts for this target.
      # In principle, any extra file type could be created here, and published.
      # Options in pants.ini allow specifying the file extension.
      with self.open_jar(jar_path, overwrite=True, compressed=True) as open_jar:
        # Write the sample file to the jar.
        open_jar.write(os.path.join(self.workdir, example_file_name), "example.txt")

      # For this target, add the path to the newly created jar to the product map, under the
      # 'extra_test_jar_example key.
      #
      # IMPORTANT: this string *must* match the string that you have set in pants.ini. Otherwise,
      # the code in 'jar_publish.py' won't be able to find this addition to the product map.
      self.context.products.get('extra_test_jar_example').add(target, self.workdir).append(jar_name)
      self.context.log.info("Made a jar: %s" % jar_path)

    # Loop over all of the targets in the graph, and select the ones that we wish to operate on.
    # This example selects all JavaLibrary targets, but different criteria can be specified below.
    for target in self.context.targets(lambda target: isinstance(target, JavaLibrary)):
      process(target)
