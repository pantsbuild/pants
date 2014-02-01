__author__ = 'Anand Madhavan'

# TODO(Anand) Remove this from pants proper when a code adjoinment mechanism exists
# or ok if/when thriftstore is open sourced as well

import os
import subprocess

from twitter.common.collections import OrderedSet
from twitter.common.dirutil import safe_mkdir

from twitter.pants.targets import JavaLibrary, JavaThriftstoreDMLLibrary

from .code_gen import CodeGen

from . import TaskError


class ThriftstoreDMLGen(CodeGen):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag("outdir"), dest="thriftstore_gen_create_outdir",
                            help="Emit thriftstore generated code in to this directory.")

  def __init__(self, context):
    CodeGen.__init__(self, context)
    self.thriftstore_codegen = context.config.get('thriftstore-dml-gen', 'thriftstore-codegen')

    self.output_dir = (context.options.thriftstore_gen_create_outdir or
                       context.config.get('thriftstore-dml-gen', 'workdir'))

    self.verbose = context.config.getbool('thriftstore-dml-gen', 'verbose')

    def create_javadeps():
      gen_info = context.config.getlist('thriftstore-dml-gen', 'javadeps')
      deps = OrderedSet()
      for dep in gen_info:
        deps.update(context.resolve(dep))
      return deps

    def is_thriftstore_dml_instance(target):
      return isinstance(target, JavaThriftstoreDMLLibrary)

    # Resolved java library targets go in javadeps
    self.javadeps = create_javadeps()

    self.gen_thriftstore_java_dir = os.path.join(self.output_dir, 'gen-thriftstore-java')

    def insert_java_dml_targets():
      self.gen_dml_jls = {}
      # Create a synthetic java library for each dml target
      for thrift_dml_lib in context.targets(is_thriftstore_dml_instance):
        # Add one generated JavaLibrary target (whose sources we will fill in later on)
        java_dml_lib = self.context.add_new_target(self.gen_thriftstore_java_dir,
                                                   JavaLibrary,
                                                   name=thrift_dml_lib.id,
                                                   sources=[],
                                                   dependencies=self.javadeps)
        java_dml_lib.add_labels('codegen')
        java_dml_lib.update_dependencies([thrift_dml_lib])
        self.gen_dml_jls[thrift_dml_lib] = java_dml_lib

      for dependee, dmls in context.dependents(is_thriftstore_dml_instance).items():
        for jl in map(lambda dml: self.gen_dml_jls[dml], dmls):
          self.updatedependencies(dependee, jl)

    insert_java_dml_targets()

  def invalidate_for(self):
    return set('java')

  def is_gentarget(self, target):
    return isinstance(target, JavaThriftstoreDMLLibrary)

  def is_forced(self, lang):
    return True

  def genlangs(self):
    return dict(java=lambda t: t.is_jvm)

  def genlang(self, lang, targets):
    bases, sources = self._calculate_sources(targets)

    safe_mkdir(self.gen_thriftstore_java_dir)

    args = [
      self.thriftstore_codegen,
      'dml',
      '-o', self.gen_thriftstore_java_dir
    ]

    if self.verbose:
      args.append('-verbose')
    args.extend(sources)
    self.context.log.debug('Executing: %s' % ' '.join(args))
    result = subprocess.call(args)
    if result != 0:
      raise TaskError('%s ... exited non-zero (%i)' % (self.thriftstore_codegen, result))

  def _calculate_sources(self, thrift_targets):
    bases = set()
    sources = set()
    def collect_sources(target):
      if self.is_gentarget(target):
        bases.add(target.target_base)
        sources.update(target.sources_relative_to_buildroot())
    for target in thrift_targets:
      target.walk(collect_sources)
    return bases, sources

  def createtarget(self, lang, gentarget, dependees):
    if lang == 'java':
      return self._create_java_target(gentarget)
    else:
      raise TaskError('Unrecognized thrift gen lang: %s' % lang)

  def _calculate_genfiles(self, sources):
    args = [
      self.thriftstore_codegen,
      'parse'
    ]
    args.extend(sources)
    self.context.log.debug('Executing: %s' % ' '.join(args))
    p = subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    output, error = p.communicate()
    result = p.wait()
    if result != 0:
      raise TaskError('%s ... exited non-zero (%i)' % (self.thriftstore_codegen, result))
    thriftstore_classes = filter(lambda s: s.strip() != '', output.split('\n'))
    self.context.log.debug('Generated files: \n\t\t%s' % '\n\t\t'.join(thriftstore_classes))
    return thriftstore_classes

  def _create_java_target(self, target):
    self.gen_dml_jls[target].sources = self._calculate_genfiles(target.sources_relative_to_buildroot())
    return self.gen_dml_jls[target]
