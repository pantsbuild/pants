# Needs the pants config file in this folder to compile:
# ./pants --pants-config-files='+["examples/src/scala/org/pantsbuild/example/scalac/compiler_options/pants.compiler_options.ini"]' ...
scala_library(
  name="with_nonfatal_warnings",
  compiler_option_sets = {"non_fatal_warnings"},
  sources=["*.scala"],
)

scala_library(
  name="with_nonfatal_warnings_and_plugin",
  compiler_option_sets = {"non_fatal_warnings"},
  sources=["*.scala"],
  dependencies=[
    'examples/src/scala/org/pantsbuild/example/scalac/plugin:simple_scalac_plugin'
  ],
   scalac_plugins=['simple_scalac_plugin'],
   scalac_plugin_args = {
     'simple_scalac_plugin': ['args', 'from', 'target', 'local']
   }
)

