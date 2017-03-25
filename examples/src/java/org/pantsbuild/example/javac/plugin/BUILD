# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

javac_plugin(
  name = 'simple_javac_plugin',
  sources = ['SimpleJavacPlugin.java'],
  dependencies = [],
  classname = 'org.pantsbuild.example.javac.plugin.SimpleJavacPlugin',
  scope='compile',
)

# The plugin will only run on this target if told to via options.
java_library(
  name = 'global',
  sources = ['Global.java'],
  dependencies = [
    ':simple_javac_plugin'
  ],
)

# The plugin will only run on this target if told to via options, but if it
# does run, it will use the args specified here.
java_library(
  name = 'global_with_local_args',
  sources = ['GlobalWithLocalArgs.java'],
  dependencies = [
    ':simple_javac_plugin'
  ],
  javac_plugin_args = {
    'simple_javac_plugin': ['args', 'from', 'target', 'global_with_local_args']
  }
)

# The plugin will always run on this target, with args specified via options.
java_library(
  name = 'local_with_global_args',
  sources = ['LocalWithGlobalArgs.java'],
  dependencies = [
    ':simple_javac_plugin'
  ],
  javac_plugins=['simple_javac_plugin']
)

# The plugin will always run on this target, with the args specified here.
java_library(
  name = 'local',
  sources = ['Local.java'],
  dependencies = [
    ':simple_javac_plugin'
  ],
  javac_plugins=['simple_javac_plugin'],
  javac_plugin_args = {
    'simple_javac_plugin': ['args', 'from', 'target', 'local']
  }
)

page(
  name='readme',
  source='README.md',
)
