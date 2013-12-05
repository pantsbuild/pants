__author__ = 'Anand Madhavan'

# TODO(Anand) Remove this from pants proper when a code adjoinment mechanism exists
# or ok if/when thriftstore is open sourced as well

import os
import subprocess

from twitter.common.collections import OrderedSet
from twitter.common.dirutil import safe_mkdir

from twitter.pants.targets import JavaLibrary, JavaThriftstoreDMLLibrary, JavaThriftLibrary
from twitter.pants.tasks import TaskError
from twitter.pants.tasks.code_gen import CodeGen

class ThriftstoreDMLGen(CodeGen):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag("outdir"), dest="thriftstore_gen_create_outdir",
                            help="Emit thriftstore generated code in to this directory.")

  def __init__(self, context):
    CodeGen.__init__(self, context)
    self.thriftstore_codegen = context.config.get('thriftstore-dml-gen', 'thriftstore-codegen')

    self.output_dir = (context.options.thriftstore_gen_create_outdir
      or context.config.get('thriftstore-dml-gen', 'workdir'))


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
      for dml_lib_target in context.targets(is_thriftstore_dml_instance):
        # Add one JavaThriftLibrary target
        thrift_dml_lib = self.context.add_new_target(dml_lib_target.target_base, # Dir where sources are relative to
                                                     JavaThriftLibrary,
                                                     name=dml_lib_target.id,
                                                     sources=dml_lib_target.sources,
                                                     dependencies=dml_lib_target.dependencies,
                                                     derived_from=dml_lib_target)
        # Add one generated JavaLibrary target (whose sources we will fill in later on)
        java_dml_lib = self.context.add_new_target(self.gen_thriftstore_java_dir,
                                                   JavaLibrary,
                                                   name=dml_lib_target.id,
                                                   sources=[],
                                                   dependencies=self.javadeps,
                                                   derived_from=dml_lib_target)
        java_dml_lib.id = dml_lib_target.id + '.thriftstore_dml_gen'
        java_dml_lib.add_labels('synthetic')
        java_dml_lib.update_dependencies([thrift_dml_lib])
        self.gen_dml_jls[dml_lib_target] = java_dml_lib

      for dependee, dmls in context.dependents(is_thriftstore_dml_instance).items():
        jls = map(lambda dml: self.gen_dml_jls[dml], dmls)
        dependee.update_dependencies(jls)

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
    if result!=0:
      raise TaskError()

  def _calculate_sources(self, thrift_targets):
    bases = set()
    sources = set()
    def collect_sources(target):
      if self.is_gentarget(target):
        bases.add(target.target_base)
        sources.update(os.path.join(target.target_base, source) for source in target.sources)
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
    if p.wait() != 0:
      raise TaskError
    thriftstore_classes = filter(lambda s: s.strip() != '', output.split('\n'))
    return thriftstore_classes

  def _create_java_target(self, target):
    source_files = [os.path.join(target.target_base, source) for source in target.sources]
    self.gen_dml_jls[target].sources = self._calculate_genfiles(source_files)
    return self.gen_dml_jls[target]
