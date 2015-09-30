# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.targets.annotation_processor import AnnotationProcessor
from pants.backend.jvm.tasks.jvm_compile.zinc.zinc_compile import ZincCompile
from pants.build_graph.target import Target
from pants.util.dirutil import safe_open


"""AnnotationProcessors are java targets that need to run in their own compilation round.

This places them on the classpath of any dependees downstream that may use them. Without
forcing a separate member type we could get a java chunk containing a mix of apt processors and
code that relied on the un-compiled apt processor in the same javac invocation. If so, javac
would not be smart enough to compile the apt processors 1st and activate them.

NB: Having a separate task for this is unnecessary with the isolated compile strategy.
"""


class AptCompile(ZincCompile):
  """Compile Java annotation processors."""
    # Well known metadata file to auto-register annotation processors with a java 1.6+ compiler
  _PROCESSOR_INFO_FILE = 'META-INF/services/javax.annotation.processing.Processor'

  _file_suffix = '.java'
  _name = 'apt'

  def __init__(self, *args, **kwargs):
    super(AptCompile, self).__init__(*args, **kwargs)
    # A directory to contain per-target subdirectories with apt processor info files.
    self._processor_info_dir = os.path.join(self.workdir, 'apt-processor-info')

  def select(self, target):
    return target.has_sources(self._file_suffix) and isinstance(target, AnnotationProcessor)

  def select_source(self, source_file_path):
    return source_file_path.endswith(self._file_suffix)

  def extra_products(self, target):
    """Override extra_products to produce an annotation processor information file."""
    ret = []
    if isinstance(target, AnnotationProcessor) and target.processors:
      root = os.path.join(self._processor_info_dir, Target.maybe_readable_identify([target]))
      processor_info_file = os.path.join(root, self._PROCESSOR_INFO_FILE)
      self._write_processor_info(processor_info_file, target.processors)
      ret.append((root, [processor_info_file]))
    return super(AptCompile, self).extra_products(target) + ret

  def _write_processor_info(self, processor_info_file, processors):
    with safe_open(processor_info_file, 'w') as f:
      for processor in processors:
        f.write('{}\n'.format(processor.strip()))
