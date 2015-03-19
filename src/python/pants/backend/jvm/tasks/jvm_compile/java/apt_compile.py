# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.targets.annotation_processor import AnnotationProcessor
from pants.backend.jvm.tasks.jvm_compile.java.java_compile import JavaCompile
from pants.base.target import Target
from pants.util.dirutil import safe_open


"""AnnotationProcessors are java targets that need to run in their own compilation round.

This places them on the classpath of any dependees downstream that may use them. Without
forcing a separate member type we could get a java chunk containing a mix of apt processors and
code that relied on the un-compiled apt processor in the same javac invocation. If so, javac
would not be smart enough to compile the apt processors 1st and activate them.
"""


class AptCompile(JavaCompile):
    # Well known metadata file to auto-register annotation processors with a java 1.6+ compiler
  _PROCESSOR_INFO_FILE = 'META-INF/services/javax.annotation.processing.Processor'

  @classmethod
  def name(cls):
    return 'apt'

  def __init__(self, *args, **kwargs):
    super(AptCompile, self).__init__(*args, **kwargs)

    # A directory independent of any other classpath which can contain a global
    # apt processor info file.
    self._processor_info_global_dir = os.path.join(self.workdir, 'apt-processor-info-global')
    # And another to contain per-target subdirectories
    self._processor_info_dir = os.path.join(self.workdir, 'apt-processor-info')

  def select(self, target):
    return target.has_sources(self._file_suffix) and isinstance(target, AnnotationProcessor)

  def extra_products(self, target):
    ret = super(AptCompile, self).extra_products(target)
    if isinstance(target, AnnotationProcessor) and target.processors:
      # The consumer of this method adds the resulting files to resources_by_target, so
      # we can safely place them in a temporary directory here.
      root = os.path.join(self._processor_info_dir, Target.maybe_readable_identify([target]))
      processor_info_file = os.path.join(root, AptCompile._PROCESSOR_INFO_FILE)
      self._write_processor_info(processor_info_file, target.processors)
      ret.append((root, [processor_info_file]))
    return ret

  def post_process(self, all_targets, relevant_targets):
    """Produce a monolithic apt processor service info file.

    This is used in further compilation rounds, and the unit-test classpath. This is
    distinct from the per-target ones we create in extra_products().
    """
    super(AptCompile, self).post_process(all_targets, relevant_targets)
    all_processors = set()
    for target in relevant_targets:
      if isinstance(target, AnnotationProcessor) and target.processors:
        all_processors.update(target.processors)
    processor_info_file = os.path.join(self._processor_info_global_dir, self._PROCESSOR_INFO_FILE)
    if os.path.exists(processor_info_file):
      with safe_open(processor_info_file, 'r') as f:
        for processor in f:
          all_processors.add(processor)
    self._write_processor_info(processor_info_file, all_processors)

    # Ensure that the processor info dir is on the classpath for all targets, so that
    # annotation processors are loaded after being compiled.
    compile_classpaths = self.context.products.get_data('compile_classpath')
    entries = [(conf, self._processor_info_global_dir) for conf in self._confs]
    compile_classpaths.add_for_targets(self.context.targets(), entries)

  def _write_processor_info(self, processor_info_file, processors):
    with safe_open(processor_info_file, 'w') as f:
      for processor in processors:
        f.write('%s\n' % processor.strip())
