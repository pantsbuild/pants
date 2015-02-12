# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import sys

from colors import cyan, green

from pants.base.config import Config, SingleFileConfig
from pants.option import custom_types
from pants.option.errors import ParseError


migrations = {
  ('jvm', 'missing_deps_target_whitelist'): ('compile.java', 'missing_deps_whitelist'),

  ('java-compile', 'partition_size_hint'): ('compile.java', 'partition_size_hint'),
  ('java-compile', 'javac_args'): ('compile.java', 'args'),
  ('java-compile', 'jvm_args'): ('compile.java', 'jvm_options'),
  ('java-compile', 'confs'): ('compile.java', 'confs'),
  ('java-compile', 'locally_changed_targets_heuristic_limit'): ('compile.java', 'changed_targets_heuristic_limit'),
  ('java-compile', 'warning_args'): ('compile.java', 'warning_args'),
  ('java-compile', 'no_warning_args'): ('compile.java', 'no_warning_args'),
  ('java-compile', 'use_nailgun'): ('compile.java', 'use_nailgun'),

  ('scala-compile', 'partition_size_hint'): ('compile.scala', 'partition_size_hint'),
  ('scala-compile', 'jvm_args'): ('compile.scala', 'jvm_options'),
  ('scala-compile', 'confs'): ('compile.scala', 'confs'),
  ('scala-compile', 'locally_changed_targets_heuristic_limit'): ('compile.scala', 'changed_targets_heuristic_limit'),
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
  ('scrooge-gen', 'jvm_args'): ('scrooge-gen', 'jvm_options'),
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
  ('scala-compile', 'compile-bootstrap-tools'): ('compile.scala', 'scalac'),  # Note: compile-bootstrap-tools is not a typo.
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

  ('backend', 'python-path'): ('DEFAULT', 'pythonpath')
}

notes = {
  ('jvm', 'missing_deps_target_whitelist'): 'This should be split into compile.java or compile.scala',
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
}


def check_config_file(path):
  cp = Config.create_parser()
  with open(path, 'r') as ini:
    cp.readfp(ini)
  config = SingleFileConfig(path, cp)

  print('Checking config file at {0} for unmigrated keys.'.format(path), file=sys.stderr)
  def section(s):
    return cyan('[{0}]'.format(s))

  for (src_section, src_key), (dst_section, dst_key) in migrations.items():
    def has_non_default_option(section, key):
      return cp.has_option(section, key) and cp.get(section, key) != cp.defaults().get(key, None)

    if config.has_section(src_section) and has_non_default_option(src_section, src_key):
      print('Found {src_key} in section {src_section}. Should be {dst_key} in section '
            '{dst_section}.'.format(src_key=green(src_key), src_section=section(src_section),
                                    dst_key=green(dst_key), dst_section=section(dst_section)),
                                    file=sys.stderr)
      if (src_section, src_key) in notes:
        print('  Note: {0}'.format(notes[(src_section, src_key)]))

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
