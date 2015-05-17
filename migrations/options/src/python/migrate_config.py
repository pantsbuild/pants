# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import sys

from colors import cyan, green, red, yellow

from pants.base.config import Config, SingleFileConfig
from pants.option import custom_types
from pants.option.errors import ParseError


migrations = {

  ('backends', 'packages'): ('DEFAULT', 'backend_packages'),
  ('backends', 'plugins'): ('DEFAULT', 'plugins'),
  ('goals', 'bootstrap_buildfiles'): ('DEFAULT', 'bootstrap_buildfiles'),

  ('jvm', 'missing_deps_target_whitelist'): ('compile.java', 'missing_deps_whitelist'),

  ('java-compile', 'partition_size_hint'): ('compile.java', 'partition_size_hint'),
  ('java-compile', 'javac_args'): ('compile.java', 'args'),
  ('java-compile', 'jvm_args'): ('compile.java', 'jvm_options'),
  ('java-compile', 'confs'): ('compile.java', 'confs'),
  ('java-compile', 'locally_changed_targets_heuristic_limit'): ('compile.java',
                                                                'changed_targets_heuristic_limit'),
  ('java-compile', 'warning_args'): ('compile.java', 'warning_args'),
  ('java-compile', 'no_warning_args'): ('compile.java', 'no_warning_args'),
  ('java-compile', 'use_nailgun'): ('compile.java', 'use_nailgun'),

  ('scala-compile', 'partition_size_hint'): ('compile.scala', 'partition_size_hint'),
  ('scala-compile', 'jvm_args'): ('compile.scala', 'jvm_options'),
  ('scala-compile', 'confs'): ('compile.scala', 'confs'),
  ('scala-compile', 'locally_changed_targets_heuristic_limit'): ('compile.scala',
                                                                 'changed_targets_heuristic_limit'),
  ('scala-compile', 'warning_args'): ('compile.scala', 'warning_args'),
  ('scala-compile', 'no_warning_args'): ('compile.scala', 'no_warning_args'),
  ('scala-compile', 'runtime-deps'): ('compile.scala', 'runtime-deps'),
  ('scala-compile', 'use_nailgun'): ('compile.scala', 'use_nailgun'),
  ('scala-compile', 'args'): ('compile.scala', 'args'),

  ('javadoc-gen', 'include_codegen'): ('gen.javadoc', 'include_codegen'),
  ('scaladoc-gen', 'include_codegen'): ('gen.scaladoc', 'include_codegen'),

  ('nailgun', 'autokill'): ('DEFAULT', 'kill_nailguns'),

  ('jvm-run', 'jvm_args'): ('run.jvm', 'jvm_options'),
  ('benchmark-run', 'jvm_args'): ('bench', 'jvm_options'),
  ('specs-run', 'jvm_args'): ('test.specs', 'jvm_options'),
  ('junit-run', 'jvm_args'): ('test.junit', 'jvm_options'),
  ('scala-repl', 'jvm_args'): ('repl.scala', 'jvm_options'),
  ('ivy-resolve', 'jvm_args'): ('resolve.ivy', 'jvm_options'),

  ('jvm-run', 'confs'): ('run.jvm', 'confs'),
  ('benchmark-run', 'confs'): ('bench', 'confs'),
  ('specs-run', 'confs'): ('test.specs', 'confs'),
  ('junit-run', 'confs'): ('test.junit', 'confs'),
  ('scala-repl', 'confs'): ('repl.scala', 'confs'),
  ('ivy-resolve', 'confs'): ('resolve.ivy', 'confs'),

  ('scala-repl', 'args'): ('repl.scala', 'args'),

  ('checkstyle', 'bootstrap-tools'): ('compile.checkstyle', 'bootstrap_tools'),
  ('checkstyle', 'configuration'): ('compile.checkstyle', 'configuration'),
  ('checkstyle', 'properties'): ('compile.checkstyle', 'properties'),

  ('scalastyle', 'config'): ('compile.scalastyle', 'config'),
  ('scalastyle', 'excludes'): ('compile.scalastyle', 'excludes'),

  # These must now be defined for each JvmTask subtask, so we temporarily put them
  # in the DEFAULT section as a convenience.
  # These will soon move into a subsystem, which will fix this.
  ('jvm', 'debug_config'): ('DEFAULT', 'debug_config'),
  ('jvm', 'debug_port'): ('DEFAULT', 'debug_port'),

  ('scala-compile', 'scalac-plugins'): ('compile.scala', 'plugins'),
  ('scala-compile', 'scalac-plugin-args'): ('compile.scala', 'plugin_args'),

  ('markdown-to-html', 'extensions'): ('markdown', 'extensions'),
  ('markdown-to-html', 'code-style'): ('markdown', 'code_style'),

  # Note: This assumes that ConfluencePublish is registered as the only task in a
  #       goal called 'confluence'.  Adjust if this is not the case in your pants.ini.
  ('confluence-publish', 'url'): ('confluence', 'url'),

  # JVM tool migrations.
  ('antlr-gen', 'javadeps'): ('gen.antlr', 'antlr3'),
  ('antlr4-gen', 'javadeps'): ('gen.antlr', 'antlr4'),
  ('scrooge-gen', 'bootstrap-tools'): ('gen.scrooge', 'scrooge'),
  ('thrift-linter', 'bootstrap-tools'): ('thrift-linter', 'scrooge_linter'),
  ('wire-gen', 'bootstrap-tools'): ('gen.wire', 'wire_compiler'),
  ('benchmark-run', 'bootstrap-tools'): ('bench', 'benchmark_tool'),
  ('benchmark-run', 'agent-bootstrap-tools'): ('bench', 'benchmark_agent'),
  ('compile.checkstyle', 'bootstrap-tools'): ('compile.checkstyle', 'checkstyle'),
  ('ivy-resolve', 'bootstrap-tools'): ('resolve.ivy', 'xalan'),
  ('jar-tool', 'bootstrap-tools'): ('DEFAULT', 'jar-tool'),
  ('junit-run', 'junit-bootstrap-tools'): ('test.junit', 'junit'),
  ('junit-run', 'emma-bootstrap-tools'): ('test.junit', 'emma'),
  ('junit-run', 'cobertura-bootstrap-tools'): ('test.junit', 'cobertura'),
  ('java-compile', 'jmake-bootstrap-tools'): ('compile.java', 'jmake'),
  ('java-compile', 'compiler-bootstrap-tools'): ('compile.java', 'java_compiler'),
  # Note: compile-bootstrap-tools is not a typo.
  ('scala-compile', 'compile-bootstrap-tools'): ('compile.scala', 'scalac'),
  ('scala-compile', 'zinc-bootstrap-tools'): ('compile.scala', 'zinc'),
  ('scala-compile', 'scalac-plugin-bootstrap-tools'): ('compile.scala', 'plugin_jars'),
  ('scala-repl', 'bootstrap-tools'): ('repl.scala', 'scala_repl'),
  ('specs-run', 'bootstrap-tools'): ('test.specs', 'specs'),

  # Artifact cache spec migration.
  ('dx-tool', 'read_artifact_caches'): ('dex', 'read_artifact_caches'),
  ('thrift-gen', 'read_artifact_caches'): ('gen.thrift', 'read_artifact_caches'),
  ('ivy-resolve', 'read_artifact_caches'): ('resolve.ivy', 'read_artifact_caches'),
  ('java-compile', 'read_artifact_caches'): ('compile.java', 'read_artifact_caches'),
  ('scala-compile', 'read_artifact_caches'): ('compile.scala', 'read_artifact_caches'),

  ('dx-tool', 'write_artifact_caches'): ('dex', 'write_artifact_caches'),
  ('thrift-gen', 'write_artifact_caches'): ('gen.thrift', 'write_artifact_caches'),
  ('ivy-resolve', 'write_artifact_caches'): ('resolve.ivy', 'write_artifact_caches'),
  ('java-compile', 'write_artifact_caches'): ('compile.java', 'write_artifact_caches'),
  ('scala-compile', 'write_artifact_caches'): ('compile.scala', 'write_artifact_caches'),

  ('protobuf-gen', 'version'): ('gen.protoc', 'version'),
  ('protobuf-gen', 'supportdir'): ('gen.protoc', 'supportdir'),
  ('protobuf-gen', 'plugins'): ('gen.protoc', 'plugins'),
  ('protobuf-gen', 'javadeps'): ('gen.protoc', 'javadeps'),
  ('protobuf-gen', 'pythondeps'): ('gen.protoc', 'pythondeps'),

  ('thrift-gen', 'strict'): ('gen.thrift', 'strict'),
  ('thrift-gen', 'supportdir'): ('gen.thrift', 'supportdir'),
  ('thrift-gen', 'version'): ('gen.thrift', 'version'),
  ('thrift-gen', 'java'): ('gen.thrift', 'java'),
  ('thrift-gen', 'python'): ('gen.thrift', 'python'),

  ('backend', 'python-path'): ('DEFAULT', 'pythonpath'),

  ('python-ipython', 'entry-point'): ('repl.py', 'ipython_entry_point'),
  ('python-ipython', 'requirements'): ('repl.py', 'ipython_requirements'),

  ('jar-publish', 'restrict_push_branches'): ('publish.jar', 'restrict_push_branches'),
  ('jar-publish', 'ivy_jvmargs'): ('publish.jar', 'jvm_options'),
  ('jar-publish', 'repos'): ('publish.jar', 'repos'),
  ('jar-publish', 'publish_extras'): ('publish.jar', 'publish_extras'),

  ('publish', 'individual_plugins'): ('publish.jar', 'individual_plugins'),
  ('publish', 'ivy_settings'): ('publish.jar', 'ivy_settings'),
  ('publish', 'jvm_options'): ('publish.jar', 'jvm_options'),
  ('publish', 'publish_extras'): ('publish.jar', 'publish_extras'),
  ('publish', 'push_postscript'): ('publish.jar', 'push_postscript'),
  ('publish', 'repos'): ('publish.jar', 'repos'),
  ('publish', 'restrict_push_branches'): ('publish.jar', 'restrict_push_branches'),

  # Three changes are pertinent to migrate 'ide' to both idea and & eclipse. I tried to capture
  # that in notes
  ('ide', 'python_source_paths'): ('idea', 'python_source_paths'),
  ('ide', 'python_lib_paths'): ('idea', 'python_lib_paths'),
  ('ide', 'python_test_paths'): ('idea', 'python_test_paths'),
  ('ide', 'extra_jvm_source_paths'): ('idea', 'extra_jvm_source_paths'),
  ('ide', 'extra_jvm_test_paths'): ('idea', 'extra_jvm_test_paths'),
  ('ide', 'debug_port'): ('idea', 'debug_port'),

  ('cache', 'compression'): ('DEFAULT', 'cache_compression'),

  ('reporting', 'reports_template_dir'): ('reporting', 'template_dir'),

  ('DEFAULT', 'stats_upload_url'): ('run-tracker', 'stats_upload_url'),
  ('DEFAULT', 'stats_upload_timeout'): ('run-tracker', 'stats_upload_timeout'),
  ('DEFAULT', 'num_foreground_workers'): ('run-tracker', 'num_foreground_workers'),
  ('DEFAULT', 'num_background_workers'): ('run-tracker', 'num_background_workers'),

  # These changes migrate all possible scoped configuration of --ng-daemons to --use-nailgun leaf
  # options.
  ('DEFAULT', 'ng_daemons'): ('DEFAULT', 'use_nailgun'),

  # NB: binary.binary -> binary is a leaf scope
  ('binary', 'ng_daemons'): ('binary', 'use_nailgun'),
  ('binary.dex', 'ng_daemons'): ('binary.dex', 'use_nailgun'),
  ('binary.dup', 'ng_daemons'): ('binary.dup', 'use_nailgun'),

  # NB: bundle.bundle -> bundle is a leaf scope
  ('bundle', 'ng_daemons'): ('bundle', 'use_nailgun'),
  ('bundle.dup', 'ng_daemons'): ('bundle.dup', 'use_nailgun'),

  ('compile', 'ng_daemons'): None,  # Intermediate scope - note only, no direct migration path
  ('compile.scalastyle', 'ng_daemons'): ('compile.scalastyle', 'use_nailgun'),
  ('compile.scala', 'ng_daemons'): ('compile.scala', 'use_nailgun'),
  ('compile.apt', 'ng_daemons'): ('compile.apt', 'use_nailgun'),
  ('compile.java', 'ng_daemons'): ('compile.java', 'use_nailgun'),
  ('compile.checkstyle', 'ng_daemons'): ('compile.checkstyle', 'use_nailgun'),

  ('detect-duplicates', 'ng_daemons'): ('detect-duplicates', 'use_nailgun'),

  ('gen', 'ng_daemons'): None,  # Intermediate scope - note only, no direct migration path
  ('gen.antlr', 'ng_daemons'): ('gen.antlr', 'use_nailgun'),
  ('gen.jaxb', 'ng_daemons'): ('gen.jaxb', 'use_nailgun'),
  ('gen.scrooge', 'ng_daemons'): ('gen.scrooge', 'use_nailgun'),

  ('imports', 'ng_daemons'): None,  # Intermediate scope - note only, no direct migration path
  ('imports.ivy-imports', 'ng_daemons'): ('imports.ivy-imports', 'use_nailgun'),

  ('jar', 'ng_daemons'): ('jar', 'use_nailgun'),
  ('publish', 'ng_daemons'): ('publish', 'use_nailgun'),

  ('resolve', 'ng_daemons'): None,  # Intermediate scope - note only, no direct migration path
  ('resolve.ivy', 'ng_daemons'): ('resolve.ivy', 'use_nailgun'),

  ('thrift-linter', 'ng_daemons'): ('thrift-linter', 'use_nailgun'),

  # Migration of the scrooge contrib module to the new options system.
  ('java-thrift-library', 'compiler'): ('DEFAULT', 'thrift_default_compiler'),
  ('java-thrift-library', 'language'): ('DEFAULT', 'thrift_default_language'),
  ('java-thrift-library', 'rpc_style'): ('DEFAULT', 'thrift_default_rpc_style'),
  ('scrooge-gen', 'jvm_args'): ('gen.scrooge', 'jvm_options'),
  ('scrooge-gen', 'jvm_options'): ('gen.scrooge', 'jvm_options'),
  ('scrooge-gen', 'strict'): ('gen.scrooge', 'strict'),
  ('scrooge-gen', 'verbose'): ('gen.scrooge', 'verbose'),
  ('thrift-linter', 'strict'): ('thrift-linter', 'strict_default'),
  # NB: For the following two options, see the notes below.
  ('scrooge-gen', 'scala'): ('gen.scrooge', 'service_deps'),
  ('scrooge-gen', 'java'): ('gen.scrooge', 'service_deps'),

  # jar-tool subsystem.
  ('jar-tool', 'bootstrap-tools'): ('jar-tool', 'jar-tool'),
  ('jar-tool', 'jvm_args'): ('jar-tool', 'jvm_options'),

  # Technically 'indices' and 'indexes' are both acceptable plural forms of 'index'. However
  # usage has led to the former being used primarily for mathematical indices and the latter
  # for book indexes, database indexes and the like.
  ('python-repos', 'indices'): ('python-repos', 'indexes'),

  ('ragel-gen', 'supportdir'): ('gen.ragel', 'supportdir'),
  ('ragel-gen', 'version'): ('gen.ragel', 'version'),

  ('prepare-resources', 'confs'): ('resources.prepare', 'confs'),

  ('compile.scala', 'runtime-deps'): ('scala-platform', 'runtime'),
  ('compile.scala', 'scalac'): ('scala-platform', 'scalac'),
}

ng_daemons_note = ('The global "ng_daemons" option has been replaced by a "use_nailgun" option '
                   'local to each task that can use a nailgun.  A default can no longer be '
                   'specified at intermediate scopes; ie: "compile" when the option is present in '
                   '"compile.apt", "compile.checkstyle", "compile.java", "compile.scala" and '
                   '"compile.scalastyle".  You must over-ride in each nailgun task section that '
                   'should not use the default "use_nailgun" value of sTrue.  You can possibly '
                   'limit the number of overrides by inverting the default with a DEFAULT section '
                   'value of False.')

scrooge_gen_deps_note = ('The scrooge-gen per-language config fields have been refactored into '
                         'two options: one for service deps, and one for structs deps.')

notes = {
  ('jvm', 'missing_deps_target_whitelist'): 'This should be split into compile.java or '
                                            'compile.scala',
  ('jvm', 'debug_port'): 'For now must be defined for each JvmTask subtask separately.  Will soon '
                         'move to a subsystem, which will fix this requirement.',
  ('jvm', 'debug_args'): 'For now must be defined for each JvmTask subtask separately.  Will soon '
                         'move to a subsystem, which will fix this requirement.',
  ('java-compile', 'javac_args'): 'source and target args should be moved to separate source: and '
                                  'target: options. Other args should be placed in args: and '
                                  'prefixed with -C.',
  ('jar-tool', 'bootstrap_tools'): 'Each JarTask sub-task can define this in its own section. or '
                                   'this can be defined for everyone in the DEFAULT section.',
  ('ivy-resolve', 'jvm_args'): 'If needed, this should be repeated in resolve.ivy, '
                               'bootstrap.bootstrap-jvm-tools and imports.ivy-imports '
                               '(as jvm_options). Easiest way to do this is to define '
                               'ivy_jvm_options in DEFAULT and then interpolate it: '
                               'jvm_options: %(ivy_jvm_options)s',
  ('protobuf-gen', 'version'): 'The behavior of the "version" and "javadeps" parameters '
                               'have changed.\n  '
                               'The old behavior to was to append the  "version" paraemter to the '
                               'target name \'protobuf-\' as the default for "javadeps".  Now '
                               '"javadeps" defaults to the value \'protobuf-java\'.',
  ('protobuf-gen', 'plugins'): 'The behavior of the "plugins" parameter has changed. '
                               'The old behavior was to unconditionally append "_protobuf" to the '
                               'end of the plugin name.  This will not work for plugins that have '
                               'a name that does not end in "_protobuf".',
  ('thrift-gen', 'verbose'): 'This flag is no longer supported. Use -ldebug instead.',
  ('ide', 'python_source_path'): 'python_source_path now must be specified separately for idea and '
                                 'eclipse goals.',
  ('ide', 'python_lib_paths'): 'python_lib_path now must be specified separately for idea and '
                              'eclipse goals.',
  ('ide', 'python_test_paths'): 'python_test_path now must be specified separately for idea and '
                               'eclipse goals.',
  ('ide', 'extra_jvm_source_paths'): 'extra_jvm_source_paths now must be specified separately for '
                                     'idea and eclipse goals.',
  ('ide', 'extra_jvm_test_paths'): 'extra_jvm_test_paths now must be specified separately for '
                                   'idea and eclipse goals.',
  ('ide', 'debug_port'):       'debug_port now must be specified separately for idea and eclipse '
                               'goals.  Also, IDE goals now use their own debug setting and do not '
                               'inherit from jvm configuration.',

  ('tasks', 'build_invalidator'): 'This is no longer configurable. The default will be used.',

  ('compile', 'ng_daemons'): ng_daemons_note,
  ('gen', 'ng_daemons'): ng_daemons_note,
  ('imports', 'ng_daemons'): ng_daemons_note,
  ('resolve', 'ng_daemons'): ng_daemons_note,
  ('scrooge-gen', 'scala'): scrooge_gen_deps_note,
  ('scrooge-gen', 'java'): scrooge_gen_deps_note,
}


def check_config_file(path):
  cp = Config.create_parser()
  with open(path, 'r') as ini:
    cp.readfp(ini)
  config = SingleFileConfig(path, cp)

  print('Checking config file at {0} for unmigrated keys.'.format(path), file=sys.stderr)
  def section(s):
    return cyan('[{0}]'.format(s))

  for (src_section, src_key), dst in migrations.items():
    def has_explicit_option(section, key):
      # David tried to avoid poking into cp's guts in https://rbcommons.com/s/twitter/r/1451/ but
      # that approach fails for the important case of boolean options.  Since this is a ~short term
      # tool and its highly likely its lifetime will be shorter than the time the private
      # ConfigParser_sections API we use here changes, its worth the risk.
      return cp.has_section(section) and (key in cp._sections[section])

    if has_explicit_option(src_section, src_key):
      if dst is not None:
        dst_section, dst_key = dst
        print('Found {src_key} in section {src_section}. Should be {dst_key} in section '
              '{dst_section}.'.format(src_key=green(src_key), src_section=section(src_section),
                                      dst_key=green(dst_key), dst_section=section(dst_section)),
                                      file=sys.stderr)
      elif (src_section, src_key) not in notes:
        print('Found {src_key} in section {src_section} and there is no automated migration path'
              'for this option.  Please consult the '
              'codebase.'.format(src_key=red(src_key), src_section=red(src_section)))

      if (src_section, src_key) in notes:
        print('  Note: {0}'.format(yellow(notes[(src_section, src_key)])))

  # Check that all values are parseable.
  for sec in ['DEFAULT'] + cp.sections():
    for key, value in cp.items(sec):
      value = value.strip()
      if value.startswith('['):
        try:
          custom_types.list_type(value)
        except ParseError:
          print('Value of {key} in section {section} is not a valid '
                'JSON list.'.format(key=green(key), section=section(sec)))
      elif value.startswith('{'):
        try:
          custom_types.dict_type(value)
        except ParseError:
          print('Value of {key} in section {section} is not a valid '
                'JSON object.'.format(key=green(key), section=section(sec)))


if __name__ == '__main__':
  if len(sys.argv) > 2:
    print('Usage: migrate_config.py [path to pants.ini file]', file=sys.stderr)
    sys.exit(1)
  elif len(sys.argv) > 1:
    path = sys.argv[1]
  else:
    path = './pants.ini'
  check_config_file(path)
