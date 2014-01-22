
import os
import shlex

from twitter.common.dirutil import safe_open

from twitter.pants.base.target import Target
from twitter.pants.base.workunit import WorkUnit
from twitter.pants.tasks import TaskError
from twitter.pants.tasks.jvm_compile.analysis_tools import AnalysisTools
from twitter.pants.tasks.jvm_compile.java.jmake_analysis import JMakeAnalysis
from twitter.pants.tasks.jvm_compile.java.jmake_analysis_parser import JMakeAnalysisParser
from twitter.pants.tasks.jvm_compile.jvm_compile import JvmCompile


# From http://kenai.com/projects/jmake/sources/mercurial/content/src/com/sun/tools/jmake/Main.java?rev=26
# Main.mainExternal docs.
_JMAKE_ERROR_CODES = {
   -1: 'invalid command line option detected',
   -2: 'error reading command file',
   -3: 'project database corrupted',
   -4: 'error initializing or calling the compiler',
   -5: 'compilation error',
   -6: 'error parsing a class file',
   -7: 'file not found',
   -8: 'I/O exception',
   -9: 'internal jmake exception',
  -10: 'deduced and actual class name mismatch',
  -11: 'invalid source file extension',
  -12: 'a class in a JAR is found dependent on a class with the .java source',
  -13: 'more than one entry for the same class is found in the project',
  -20: 'internal Java error (caused by java.lang.InternalError)',
  -30: 'internal Java error (caused by java.lang.RuntimeException).'
}
# When executed via a subprocess return codes will be treated as unsigned
_JMAKE_ERROR_CODES.update((256+code, msg) for code, msg in _JMAKE_ERROR_CODES.items())


class JavaCompile(JvmCompile):
  _language = 'java'
  _file_suffix = '.java'
  _config_section = 'java-compile'

    # Well known metadata file to auto-register annotation processors with a java 1.6+ compiler
  _PROCESSOR_INFO_FILE = 'META-INF/services/javax.annotation.processing.Processor'


  _JMAKE_MAIN = 'com.sun.tools.jmake.Main'

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    JvmCompile.setup_parser(JavaCompile, option_group, args, mkflag)

    option_group.add_option(mkflag("args"), dest="java_compile_args", action="append",
                            help="Pass these extra args to javac.")

  def __init__(self, context):
    JvmCompile.__init__(self, context, workdir=context.config.get('java-compile', 'nailgun_dir'))

    self._depfile = os.path.join(self._analysis_dir, 'global_depfile')

    self._jmake_bootstrap_key = 'jmake'
    external_tools = context.config.getlist('java-compile', 'jmake-bootstrap-tools', default=[':jmake'])
    self.register_jvm_tool(self._jmake_bootstrap_key, external_tools)

    self._compiler_bootstrap_key = 'java-compiler'
    compiler_bootstrap_tools = context.config.getlist('java-compile', 'compiler-bootstrap-tools',
                                                      default=[':java-compiler'])
    self.register_jvm_tool(self._compiler_bootstrap_key, compiler_bootstrap_tools)

    self._javac_opts = []
    if context.options.java_compile_args:
      for arg in context.options.java_compile_args:
        self._javac_opts.extend(shlex.split(arg))
    else:
      self._javac_opts.extend(context.config.getlist('java-compile', 'javac_args', default=[]))

  def create_analysis_tools(self):
    return AnalysisTools(self.context, JMakeAnalysisParser(self._classes_dir), JMakeAnalysis)

  def extra_products(self, target):
    ret = []
    # TODO(John Sirois): Map target.resources in the same way.
    # 'Map' (rewrite) annotation processor service info files to the owning targets.
    if target.is_apt and target.processors:
      basedir = os.path.join(self._resources_dir, Target.maybe_readable_identify([target]))
      processor_info_file = os.path.join(basedir, JavaCompile._PROCESSOR_INFO_FILE)
      self._write_processor_info(processor_info_file, target.processors)
      ret.append((basedir, [processor_info_file]))
    return ret

  def compile(self, args, classpath, sources, classes_output_dir, analysis_file):
    jmake_classpath = self._jvm_tool_bootstrapper.get_jvm_tool_classpath(self._jmake_bootstrap_key,
                                                                         self.runjava_indivisible)
    args = [
      '-classpath', ':'.join(classpath + [self._classes_dir]),
      '-d', self._classes_dir,
      '-pdb', analysis_file,
      '-pdb-text-format',
      ]

    compiler_classpath = self._jvm_tool_bootstrapper.get_jvm_tool_classpath(self._compiler_bootstrap_key,
                                                                            self.runjava_indivisible)
    args.extend([
      '-jcpath', ':'.join(compiler_classpath),
      '-jcmainclass', 'com.twitter.common.tools.Compiler',
      ])
    args.extend(map(lambda arg: '-C%s' % arg, self._javac_opts))

    args.extend(self._args)
    args.extend(sources)
    result = self.runjava_indivisible(JavaCompile._JMAKE_MAIN,
                                      classpath=jmake_classpath,
                                      jvm_options=self._jvm_options,
                                      args=args,
                                      workunit_name='jmake',
                                      workunit_labels=[WorkUnit.COMPILER])
    if result:
      default_message = 'Unexpected error - JMake returned %d' % result
      raise TaskError(_JMAKE_ERROR_CODES.get(result, default_message))

  def post_process(self, relevant_targets):
      # Produce a monolithic apt processor service info file for further compilation rounds
      # and the unit test classpath.
      # This is distinct from the per-target ones we create in extra_products().
      all_processors = set()
      for target in relevant_targets:
        if target.is_apt and target.processors:
          all_processors.update(target.processors)
      processor_info_file = os.path.join(self._classes_dir, JavaCompile._PROCESSOR_INFO_FILE)
      if os.path.exists(processor_info_file):
        with safe_open(processor_info_file, 'r') as f:
          for processor in f:
            all_processors.add(processor)
      self._write_processor_info(processor_info_file, all_processors)

  def _write_processor_info(self, processor_info_file, processors):
    with safe_open(processor_info_file, 'w') as f:
      for processor in processors:
        f.write('%s\n' % processor.strip())
