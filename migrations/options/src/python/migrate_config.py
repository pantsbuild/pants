# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import sys

from colors import cyan, green, red, yellow

from pants.option import custom_types
from pants.option.config import Config
from pants.option.errors import ParseError


migrations = {
  ('backends', 'packages'): ('DEFAULT', 'backend_packages'),
  ('backends', 'plugins'): ('DEFAULT', 'plugins'),

  ('jvm', 'missing_deps_target_whitelist'): ('compile.jvm-dep-check', 'missing_deps_whitelist'),
  ('jvm', 'jdk_paths'): ('jvm-distributions', 'paths'),
  ('compile.java', 'missing_deps'): ('compile.jvm-dep-check', 'missing_deps'),
  ('compile.java', 'missing_direct_deps'): ('compile.jvm-dep-check', 'missing_direct_deps'),
  ('compile.java', 'missing_deps_whitelist'): ('compile.jvm-dep-check', 'missing_deps_whitelist'),
  ('compile.java', 'unnecessary_deps'): ('compile.jvm-dep-check', 'unnecessary_deps'),

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
  ('scala-compile', 'runtime_deps'): ('compile.scala', 'runtime_deps'),
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

  ('checkstyle', 'bootstrap_tools'): ('compile.checkstyle', 'bootstrap_tools'),
  ('checkstyle', 'configuration'): ('compile.checkstyle', 'configuration'),
  ('checkstyle', 'properties'): ('compile.checkstyle', 'properties'),

  ('scalastyle', 'config'): ('compile.scalastyle', 'config'),
  ('scalastyle', 'excludes'): ('compile.scalastyle', 'excludes'),

  # These must now be defined for each JvmTask subtask, so we temporarily put them
  # in the DEFAULT section as a convenience.
  # These will soon move into a subsystem, which will fix this.
  ('jvm', 'debug_config'): ('DEFAULT', 'debug_config'),
  ('jvm', 'debug_port'): ('DEFAULT', 'debug_port'),

  ('scala-compile', 'scalac_plugins'): ('compile.scala', 'plugins'),
  ('scala-compile', 'scalac_plugin_args'): ('compile.scala', 'plugin_args'),

  ('markdown-to-html', 'extensions'): ('markdown', 'extensions'),
  ('markdown-to-html', 'code_style'): ('markdown', 'code_style'),

  # Note: This assumes that ConfluencePublish is registered as the only task in a
  #       goal called 'confluence'.  Adjust if this is not the case in your pants.ini.
  ('confluence-publish', 'url'): ('confluence', 'url'),

  # JVM tool migrations.
  ('antlr-gen', 'javadeps'): ('gen.antlr', 'antlr3'),
  ('antlr4-gen', 'javadeps'): ('gen.antlr', 'antlr4'),
  ('scrooge-gen', 'bootstrap_tools'): ('gen.scrooge', 'scrooge'),
  ('thrift-linter', 'bootstrap_tools'): ('thrift-linter', 'scrooge_linter'),
  ('wire-gen', 'bootstrap_tools'): ('gen.wire', 'wire_compiler'),
  ('benchmark-run', 'bootstrap_tools'): ('bench', 'benchmark_tool'),
  ('benchmark-run', 'agent_bootstrap_tools'): ('bench', 'benchmark_agent'),
  ('compile.checkstyle', 'bootstrap_tools'): ('compile.checkstyle', 'checkstyle'),
  ('ivy-resolve', 'bootstrap_tools'): ('resolve.ivy', 'xalan'),
  ('jar-tool', 'bootstrap_tools'): ('DEFAULT', 'jar-tool'),
  ('junit-run', 'junit_bootstrap_tools'): ('test.junit', 'junit'),
  ('junit-run', 'emma_bootstrap_tools'): ('test.junit', 'emma'),
  ('junit-run', 'cobertura_bootstrap_tools'): ('test.junit', 'cobertura'),
  ('java-compile', 'jmake_bootstrap_tools'): ('compile.java', 'jmake'),
  ('java-compile', 'compiler-bootstrap-tools'): ('compile.java', 'java_compiler'),
  # Note: compile-bootstrap-tools is not a typo.
  ('scala-compile', 'compile_bootstrap_tools'): ('compile.scala', 'scalac'),
  ('scala-compile', 'zinc_bootstrap_tools'): ('compile.scala', 'zinc'),
  ('scala-compile', 'scalac_plugin_bootstrap_tools'): ('compile.scala', 'plugin_jars'),
  ('scala-repl', 'bootstrap_tools'): ('repl.scala', 'scala_repl'),
  ('specs-run', 'bootstrap_tools'): ('test.specs', 'specs'),

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

  ('python-ipython', 'entry_point'): ('repl.py', 'ipython_entry_point'),
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
  ('binary.dup', 'excludes'): ('binary.dup', 'exclude_files'),

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
  ('jar-tool', 'bootstrap_tools'): ('jar-tool', 'jar_tool'),
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

  ('DEFAULT', 'thrift_default_compiler'): ('thrift-defaults', 'compiler'),
  ('DEFAULT', 'thrift_default_language'): ('thrift-defaults', 'language'),
  ('DEFAULT', 'thrift_default_rpc_style'): ('thrift-defaults', 'rpc_style'),

  ('python-setup', 'egg_cache_dir'): ('python_setup', 'resolver_cache_dir'),
  ('DEFAULT', 'python_chroot_requirements_ttl'): ('python-setup', 'resolver_cache_ttl'),

  ('DEFAULT', 'pants_support_baseurls'): ('binaries', 'baseurls'),
  ('DEFAULT', 'pants_support_fetch_timeout_secs'): ('binaries', 'fetch_timeout_secs'),

  ('gen.thrift', 'supportdir'): ('thrift-binary', 'supportdir'),
  ('gen.thrift', 'version'): ('thrift-binary', 'version'),

  ('gen.thrift', 'java'): None,  # Notes only one to many migration: see notes below.
  ('gen.thrift', 'python'): None,  # Notes only pure deletion migration: see notes below.

  ('compile.zinc-java', 'enabled'): ('compile.java', 'use-jmake'),

  ('compile.scala', 'args'): ('compile.zinc', 'args'),

  ('compile.cpp-compile', 'cc_options'): ('compile.cpp', 'cc_options'),
  ('compile.cpp-compile', 'cc_extensions'): ('compile.cpp', 'cc_extensions'),

  ('test.junit', 'coverage_html_open'): ('test.junit', 'coverage_open'),

  # On by default.
  ('compile.apt', 'jar'): None,
  ('compile.java', 'jar'): None,
  ('compile.zinc', 'jar'): None,

  ('unknown-arguments', 'ignored'): None,

  # Tool specs, migrated from a list to a single string.
  ('bench', 'benchmark-agent'): None,
  ('bench', 'benchmark-tool'): None,
  ('binary', 'nailgun-server'): None,
  ('binary.dex', 'nailgun-server'): None,
  ('binary.dup', 'nailgun-server'): None,
  ('bootstrap.bootstrap-jvm-tools', 'jarjar'): None,
  ('bootstrap.bootstrap-jvm-tools', 'nailgun-server'): None,
  ('bundle', 'nailgun-server'): None,
  ('bundle.dup', 'nailgun-server'): None,
  ('compile.apt', 'java-compiler'): None,
  ('compile.apt', 'jmake'): None,
  ('compile.apt', 'nailgun-server'): None,
  ('compile.checkstyle', 'checkstyle'): None,
  ('compile.checkstyle', 'nailgun-server'): None,
  ('compile.java', 'java-compiler'): None,
  ('compile.java', 'jmake'): None,
  ('compile.java', 'nailgun-server'): None,
  ('compile.scalastyle', 'nailgun-server'): None,
  ('compile.scalastyle', 'scalastyle'): None,
  ('compile.zinc', 'compiler-interface'): None,
  ('compile.zinc', 'nailgun-server'): None,
  ('compile.zinc', 'plugin-jars'): None,
  ('compile.zinc', 'sbt-interface'): None,
  ('compile.zinc', 'zinc'): None,
  ('detect-duplicates', 'nailgun-server'): None,
  ('gen.antlr', 'antlr3'): None,
  ('gen.antlr', 'antlr4'): None,
  ('gen.antlr', 'nailgun-server'): None,
  ('gen.jaxb', 'nailgun-server'): None,
  ('gen.scrooge', 'nailgun-server'): None,
  ('gen.scrooge', 'scrooge-gen'): None,
  ('gen.spindle', 'nailgun-server'): None,
  ('gen.spindle', 'spindle-codegen'): None,
  ('gen.wire', 'javadeps'): None,
  ('gen.wire', 'wire-compiler'): None,
  ('imports.ivy-imports', 'nailgun-server'): None,
  ('jar', 'nailgun-server'): None,
  ('jar-tool', 'jar-tool'): None,
  ('publish.jar', 'nailgun-server'): None,
  ('repl-dirty.scala-dirty', 'scala-repl'): None,
  ('repl.scala', 'scala-repl'): None,
  ('resolve.ivy', 'nailgun-server'): None,
  ('resolve.ivy', 'xalan'): None,
  ('scala-platform', 'scalac'): None,
  ('test.junit', 'cobertura-instrument'): None,
  ('test.junit', 'cobertura-report'): None,
  ('test.junit', 'cobertura-run'): None,
  ('test.junit', 'emma'): None,
  ('test.junit', 'junit'): None,
  ('thrift-linter', 'nailgun-server'): None,
  ('thrift-linter', 'scrooge-linter'): None,

  # Global strategy removal.
  ('compile.apt', 'changed-targets-heuristic-limit'): None,
  ('compile.apt', 'partition-size-hint'): None,
  ('compile.apt', 'strategy'): None,
  ('compile.java', 'changed-targets-heuristic-limit'): None,
  ('compile.java', 'partition-size-hint'): None,
  ('compile.java', 'strategy'): None,
  ('compile.zinc', 'changed-targets-heuristic-limit'): None,
  ('compile.zinc', 'partition-size-hint'): None,
  ('compile.zinc', 'strategy'): None,

  # Jmake and Apt removal.
  ('compile.apt', 'args'): ('compile.zinc', 'args'),
  ('compile.apt', 'jvm_options'): ('compile.zinc', 'jvm_options'),
  ('compile.java', 'args'): ('compile.zinc', 'args'),
  ('compile.java', 'jvm_options'): ('compile.zinc', 'jvm_options'),

  # Renaming JarCreate's scope.  It was previously privileged to be called 'jar'. That might seem reasonable,
  # except that adding anything to the 'jar' goal (e.g., see extra_test_jar_example.py) creates the potential
  # for option shadowing.
  # Note: We probably did the "eliding a task with the same name as its goal" thing wrong. Since options are
  # inherited from outer scopes, this creates lots of potential for option shadowing. We should probably not
  # have elided the option scope (e.g., the scope should have remained jar.jar, not jar, internally), but rather
  # done the elision early, when interpreting scopes in config/cmd-line args etc.
  # TODO: Fix this?  I don't think it would be that difficult, but there might be unintended consequences.
  # For now we simply avoid it in cases where there's any likelihood of options collision occuring.
  # In practice this won't be a problem with cases where there really is only one sensible task in a goal,
  # e.g., the various ConsoleTasks.
  ('jar', 'use_nailgun'): ('jar.create', 'use_nailgun'),
  ('jar', 'nailgun_timeout_seconds'): ('jar.create', 'nailgun_timeout_seconds'),
  ('jar', 'nailgun_connect_attempts'): ('jar.create', 'nailgun_connect_attempts'),
  ('jar', 'nailgun_server'): ('jar.create', 'nailgun_server'),

  # Renaming JvmBinaryCreate's scope.  It was previously privileged to be called 'binary'.
  ('binary', 'use_nailgun'): ('binary.jvm', 'use_nailgun'),
  ('binary', 'nailgun_timeout_seconds'): ('binary.jvm', 'nailgun_timeout_seconds'),
  ('binary', 'nailgun_connect_attempts'): ('binary.jvm', 'nailgun_connect_attempts'),
  ('binary', 'nailgun_server'): ('binary.jvm', 'nailgun_server'),

  # Renaming JvmBundleCreate's scope.  It was previously privileged to be called 'bundle'.
  ('bundle', 'use_nailgun'): ('bundle.jvm', 'use_nailgun'),
  ('bundle', 'nailgun_timeout_seconds'): ('bundle.jvm', 'nailgun_timeout_seconds'),
  ('bundle', 'nailgun_connect_attempts'): ('bundle.jvm', 'nailgun_connect_attempts'),
  ('bundle', 'nailgun_server'): ('bundle.jvm', 'nailgun_server'),
  ('bundle', 'deployjar'): ('bundle.jvm', 'deployjar'),
  ('bundle', 'archive'): ('bundle.jvm', 'archive'),
  ('bundle', 'archive_prefix'): ('bundle.jvm', 'archive_prefix'),

  # Preventing shadowing of global options.
  ('compile.zinc', 'plugins'): ('compile.zinc', 'scalac_plugins'),
  ('compile.zinc', 'plugin_args'): ('compile.zinc', 'scalac_plugin_args'),
  ('gen.protoc', 'plugins'): ('gen.protoc', 'protoc_plugins'),

  # Superceded by the global --tags option.
  ('filter', 'tags'): None
}

jvm_global_strategy_removal = ('The JVM global compile strategy was removed in favor of the '
                               'isolated strategy, which uses a different set of options.')

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
compile_jar_note = ('The isolated jvm compile `jar` option is critical to performant operation '
                    'and can no longer be disabled.')

jvm_tool_spec_override = ('JVM tool classpath spec overrides have migrated from a list of target'
                          'addresses to a single target address.  To migrate a list of addresses '
                          'you\'ll need to create a new aggregator target to hold the list like '
                          'so: `target(name=<your choice>, dependencies=[<list of addresses>])` '
                          'and then point to its single address.')

notes = {
  ('jvm', 'missing_deps_target_whitelist'): 'This should be split into compile.java or '
                                            'compile.scala',
  ('jvm', 'debug_port'): 'For now must be defined for each JvmTask subtask separately.  Will soon '
                         'move to a subsystem, which will fix this requirement.',
  ('jvm', 'debug_args'): 'For now must be defined for each JvmTask subtask separately.  Will soon '
                         'move to a subsystem, which will fix this requirement.',
  ('java-compile', 'javac_args'): 'Source, target, and bootclasspath args should be specified in '
                                  'the jvm-platform subsystem. Other args can be placed in args: '
                                  'and prefixed with -C, or also be included in the jvm-platform '
                                  'args.',
  ('java-compile', 'source'): 'source and target args should be defined using the jvm-platform '
                              'subsystem, rathern than as arguments to java-compile.',
  ('java-compile', 'target'): 'source and target args should be defined using the jvm-platform '
                              'subsystem, rathern than as arguments to java-compile.',
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
  ('ide', 'debug_port'): 'debug_port now must be specified separately for idea and eclipse '
                         'goals.  Also, IDE goals now use their own debug setting and do not '
                         'inherit from jvm configuration.',

  ('tasks', 'build_invalidator'): 'This is no longer configurable. The default will be used.',

  ('compile', 'ng_daemons'): ng_daemons_note,
  ('gen', 'ng_daemons'): ng_daemons_note,
  ('imports', 'ng_daemons'): ng_daemons_note,
  ('resolve', 'ng_daemons'): ng_daemons_note,
  ('scrooge-gen', 'scala'): scrooge_gen_deps_note,
  ('scrooge-gen', 'java'): scrooge_gen_deps_note,

  ('gen.thrift', 'version'): 'You can either set the apache thrift compiler version globally for '
                             'java and python using the [thrift-binary] scope or else you can '
                             'configure the languages separately using the '
                             '[thrift-binary.gen.thrift] scope to control the version used for '
                             'java.',

  ('gen.thrift', 'java'): 'The java configuration has migrated from a single dict with 3 keys to '
                          '3 options.\n'
                          'The "gen" key has migrated to the `gen_options` option and the value '
                          'should just be the option portion of the thrift --gen argument.  For '
                          'example, if you had `"gen": "java:hashcode"` as your java dict entry '
                          'you\'d now use the top-level option `gen_options: hashcode`.\n'
                          'The "deps.structs" nested key has migrated to the `deps` option and the '
                          'value remains the same.\n'
                          'The "deps.service" nested key as migrated to the `service_deps` option '
                          'and the value remains the same, but is now optional if service deps are '
                          'the same as non-service deps.',

  ('gen.thrift', 'python'): 'The python configuration for gen.thrift has never been used and '
                            'should be removed.',

  ('resolve.ivy', 'automatic_excludes'): 'Enabled by default.',
  ('imports.ivy-imports', 'automatic_excludes'): 'Enabled by default.',

  ('compile.zinc-java', 'enabled'): 'The enabled flag has moved from "enable zinc for java" '
                                    'to "disable jmake for java", more precisely, instead of '
                                    '--compile-zinc-java-enabled, use --no-compile-java-use-jmake',
  ('compile.scala', 'args'): 'ALL `compile.scala` options have moved to `compile.zinc`.',

  ('compile.cpp-compile', 'cc_options'): 'Value used to be a string, is now a list.',
  ('compile.cpp-compile', 'cc_extensions'): 'Value used to be a string (but default was a list), '
                                            'is now a list. Values also now include the dot, e.g.,'
                                            'it\'s now .cpp, not cpp.',

  ('test.junit', 'coverage-patterns'): 'Option no longer exists. Only applied to emma coverage, '
                                       'which was removed.',
  ('test.junit', 'coverage-processor'): 'The default value for this option has changed from "emma" '
                                        'to "cobertura".',

  ('test.junit', 'coverage_console'): 'Option no longer exists. Coverage always written to stdout.',
  ('test.junit', 'coverage_html'): 'Option no longer exists. Coverage always written to html file.',
  ('test.junit', 'coverage_xml'): 'Option no longer exists. Coverage always written to xml file.',

  ('compile.apt', 'jar'): compile_jar_note,
  ('compile.java', 'jar'): compile_jar_note,
  ('compile.zinc', 'jar'): compile_jar_note,

  ('unknown-arguments', 'ignored'): 'Target name keys are now expected to be the alias used in '
                                    'BUILD files and not the target type\'s simple class name. '
                                    'For example, if you had \'JavaLibrary\' key you\'d now use '
                                    '\'java_library\' instead.',

  ('bench', 'benchmark-agent'): jvm_tool_spec_override,
  ('bench', 'benchmark-tool'): jvm_tool_spec_override,
  ('binary', 'nailgun-server'): jvm_tool_spec_override,
  ('binary.dex', 'nailgun-server'): jvm_tool_spec_override,
  ('binary.dup', 'nailgun-server'): jvm_tool_spec_override,
  ('bootstrap.bootstrap-jvm-tools', 'jarjar'): jvm_tool_spec_override,
  ('bootstrap.bootstrap-jvm-tools', 'nailgun-server'): jvm_tool_spec_override,
  ('bundle', 'nailgun-server'): jvm_tool_spec_override,
  ('bundle.dup', 'nailgun-server'): jvm_tool_spec_override,
  ('compile.apt', 'java-compiler'): jvm_tool_spec_override,
  ('compile.apt', 'jmake'): jvm_tool_spec_override,
  ('compile.apt', 'nailgun-server'): jvm_tool_spec_override,
  ('compile.checkstyle', 'checkstyle'): jvm_tool_spec_override,
  ('compile.checkstyle', 'nailgun-server'): jvm_tool_spec_override,
  ('compile.java', 'java-compiler'): jvm_tool_spec_override,
  ('compile.java', 'jmake'): jvm_tool_spec_override,
  ('compile.java', 'nailgun-server'): jvm_tool_spec_override,
  ('compile.scalastyle', 'nailgun-server'): jvm_tool_spec_override,
  ('compile.scalastyle', 'scalastyle'): jvm_tool_spec_override,
  ('compile.zinc', 'compiler-interface'): jvm_tool_spec_override,
  ('compile.zinc', 'nailgun-server'): jvm_tool_spec_override,
  ('compile.zinc', 'plugin-jars'): jvm_tool_spec_override,
  ('compile.zinc', 'sbt-interface'): jvm_tool_spec_override,
  ('compile.zinc', 'zinc'): jvm_tool_spec_override,
  ('detect-duplicates', 'nailgun-server'): jvm_tool_spec_override,
  ('gen.antlr', 'antlr3'): jvm_tool_spec_override,
  ('gen.antlr', 'antlr4'): jvm_tool_spec_override,
  ('gen.antlr', 'nailgun-server'): jvm_tool_spec_override,
  ('gen.jaxb', 'nailgun-server'): jvm_tool_spec_override,
  ('gen.scrooge', 'nailgun-server'): jvm_tool_spec_override,
  ('gen.scrooge', 'scrooge-gen'): jvm_tool_spec_override,
  ('gen.spindle', 'nailgun-server'): jvm_tool_spec_override,
  ('gen.spindle', 'spindle-codegen'): jvm_tool_spec_override,
  ('gen.wire', 'javadeps'): jvm_tool_spec_override,
  ('gen.wire', 'wire-compiler'): jvm_tool_spec_override,
  ('imports.ivy-imports', 'nailgun-server'): jvm_tool_spec_override,
  ('jar', 'nailgun-server'): jvm_tool_spec_override,
  ('jar-tool', 'jar-tool'): jvm_tool_spec_override,
  ('publish.jar', 'nailgun-server'): jvm_tool_spec_override,
  ('repl-dirty.scala-dirty', 'scala-repl'): jvm_tool_spec_override,
  ('repl.scala', 'scala-repl'): jvm_tool_spec_override,
  ('resolve.ivy', 'nailgun-server'): jvm_tool_spec_override,
  ('resolve.ivy', 'xalan'): jvm_tool_spec_override,
  ('scala-platform', 'scalac'): jvm_tool_spec_override,
  ('test.junit', 'cobertura-instrument'): jvm_tool_spec_override,
  ('test.junit', 'cobertura-report'): jvm_tool_spec_override,
  ('test.junit', 'cobertura-run'): jvm_tool_spec_override,
  ('test.junit', 'emma'): jvm_tool_spec_override,
  ('test.junit', 'junit'): jvm_tool_spec_override,
  ('thrift-linter', 'nailgun-server'): jvm_tool_spec_override,
  ('thrift-linter', 'scrooge-linter'): jvm_tool_spec_override,

  # Global strategy removal.
  ('compile.apt', 'changed-targets-heuristic-limit'): jvm_global_strategy_removal,
  ('compile.apt', 'partition-size-hint'): jvm_global_strategy_removal,
  ('compile.apt', 'strategy'): jvm_global_strategy_removal,
  ('compile.java', 'changed-targets-heuristic-limit'): jvm_global_strategy_removal,
  ('compile.java', 'partition-size-hint'): jvm_global_strategy_removal,
  ('compile.java', 'strategy'): jvm_global_strategy_removal,
  ('compile.zinc', 'changed-targets-heuristic-limit'): jvm_global_strategy_removal,
  ('compile.zinc', 'partition-size-hint'): jvm_global_strategy_removal,
  ('compile.zinc', 'strategy'): jvm_global_strategy_removal,

  ('bootstrap.bootstrap-jvm-tools', 'jvm-options'): 'This previously shadowed the same option '
                                                    'registered by IvyTaskMixin.  If you want to '
                                                    'specifically configure the shader, use '
                                                    'shader-jvm-options.'
}


def check_option(cp, src, dst):
  def has_explicit_option(section, key):
    # David tried to avoid poking into cp's guts in https://rbcommons.com/s/twitter/r/1451/ but
    # that approach fails for the important case of boolean options.  Since this is a ~short term
    # tool and its highly likely its lifetime will be shorter than the time the private
    # ConfigParser_sections API we use here changes, it's worth the risk.
    if section == 'DEFAULT':
      # NB: The 'DEFAULT' section is not tracked via `has_section` or `_sections`, so we use a
      # different API to check for an explicit default.
      return key in cp.defaults()
    else:
      return cp.has_section(section) and (key in cp._sections[section])

  def sect(s):
    return cyan('[{}]'.format(s))

  src_section, src_key = src
  if has_explicit_option(src_section, src_key):
    if dst is not None:
      dst_section, dst_key = dst
      print('Found {src_key} in section {src_section}. Should be {dst_key} in section '
            '{dst_section}.'.format(src_key=green(src_key), src_section=sect(src_section),
                                    dst_key=green(dst_key), dst_section=sect(dst_section)),
            file=sys.stderr)
    elif src not in notes:
      print('Found {src_key} in section {src_section} and there is no automated migration path'
            'for this option.  Please consult the '
            'codebase.'.format(src_key=red(src_key), src_section=red(src_section)))

    if (src_section, src_key) in notes:
      print('  Note for {src_key} in section {src_section}: {note}'
            .format(src_key=green(src_key),
                    src_section=sect(src_section),
                    note=yellow(notes[(src_section, src_key)])))


def check_config_file(path):
  cp = Config._create_parser()
  with open(path, 'r') as ini:
    cp.readfp(ini)

  print('Checking config file at {} for unmigrated keys.'.format(path), file=sys.stderr)

  def section(s):
    return cyan('[{}]'.format(s))

  for src, dst in migrations.items():
    check_option(cp, src, dst)

  # Special-case handling of per-task subsystem options, so we can sweep them up in all
  # sections easily.

  def check_task_subsystem_options(subsystem_sec, options_map, sections=None):
    sections = sections or cp.sections()
    for src_sec in ['DEFAULT'] + sections:
      dst_sec = subsystem_sec if src_sec == 'DEFAULT' else '{}.{}'.format(subsystem_sec, src_sec)
      for src_key, dst_key in options_map.items():
        check_option(cp, (src_sec, src_key), (dst_sec, dst_key))

  artifact_cache_options_map = {
    'read_from_artifact_cache': 'read',
    'write_to_artifact_cache': 'write',
    'overwrite_cache_artifacts': 'overwrite',
    'read_artifact_caches': 'read_from',
    'write_artifact_caches': 'write_to',
    'cache_compression': 'compression_level',
  }
  check_task_subsystem_options('cache', artifact_cache_options_map)

  jvm_options_map = {
    'jvm_options': 'options',
    'args': 'program_args',
    'debug': 'debug',
    'debug_port': 'debug_port',
    'debug_args': 'debug_args',
  }
  jvm_options_sections = [
    'repl.scala', 'test.junit', 'run.jvm', 'bench', 'doc.javadoc', 'doc.scaladoc'
  ]
  check_task_subsystem_options('jvm', jvm_options_map, sections=jvm_options_sections)

  # Check that all values are parseable.
  for sec in ['DEFAULT'] + cp.sections():
    for key, value in cp.items(sec):
      value = value.strip()
      if value.startswith('['):
        try:
          custom_types.list_option(value)
        except ParseError:
          print('Value of {key} in section {section} is not a valid '
                'JSON list.'.format(key=green(key), section=section(sec)))
      elif value.startswith('{'):
        try:
          custom_types.dict_option(value)
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
