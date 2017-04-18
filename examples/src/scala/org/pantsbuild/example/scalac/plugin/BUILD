# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

scalac_plugin(
  name='simple_scalac_plugin',
  plugin='simple_scalac_plugin',
  classname='org.pantsbuild.example.scalac.plugin.SimpleScalacPlugin',
  sources=['SimpleScalacPlugin.scala'],
  dependencies=[':other_simple_scalac_plugin'],
  scope='compile',
)

scalac_plugin(
  name='other_simple_scalac_plugin',
  plugin='other_simple_scalac_plugin',
  classname='org.pantsbuild.example.scalac.plugin.OtherSimpleScalacPlugin',
  sources=['OtherSimpleScalacPlugin.scala'],
  scope='compile',
)

# The plugin will only run on this target if told to via options.
scala_library(
  name = 'global',
  sources = ['Global.scala'],
  dependencies = [
    ':simple_scalac_plugin'
  ],
)

# The plugin will only run on this target if told to via options, but if it
# does run, it will use the args specified here.
scala_library(
  name = 'global_with_local_args',
  sources = ['GlobalWithLocalArgs.scala'],
  dependencies = [
    ':simple_scalac_plugin'
  ],
  scalac_plugin_args = {
    'simple_scalac_plugin': ['args', 'from', 'target', 'global_with_local_args']
  }
)

# The plugin will always run on this target, with args specified via options.
scala_library(
  name = 'local_with_global_args',
  sources = ['LocalWithGlobalArgs.scala'],
  dependencies = [
    ':simple_scalac_plugin'
  ],
  scalac_plugins=['simple_scalac_plugin']
)

# The plugin will always run on this target, with the args specified here.
scala_library(
  name = 'local',
  sources = ['Local.scala'],
  dependencies = [
    ':simple_scalac_plugin'
  ],
  scalac_plugins=['simple_scalac_plugin'],
  scalac_plugin_args = {
    'simple_scalac_plugin': ['args', 'from', 'target', 'local']
  }
)

page(
  name='readme',
  source='README.md',
)
