import os
from twitter.pants.targets.scala_library import ScalaLibrary
from twitter.pants.tasks.jvm_compile.analysis_tools import AnalysisTools
from twitter.pants.tasks.jvm_compile.jvm_compile import JvmCompile
from twitter.pants.tasks.jvm_compile.scala.zinc_analysis import ZincAnalysis
from twitter.pants.tasks.jvm_compile.scala.zinc_analysis_parser import ZincAnalysisParser
from twitter.pants.tasks.jvm_compile.scala.zinc_utils import ZincUtils


class ScalaCompile(JvmCompile):
  _language = 'scala'
  _file_suffix = '.scala'
  _config_section = 'scala-compile'

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    JvmCompile.setup_parser(ScalaCompile, option_group, args, mkflag)

    option_group.add_option(mkflag('plugins'), dest='plugins', default=None,
      action='append', help='Use these scalac plugins. Default is set in pants.ini.')

  def __init__(self, context):
    JvmCompile.__init__(self, context, workdir=context.config.get('scala-compile', 'nailgun_dir'))

    # Set up the zinc utils.
    color = not context.options.no_color
    self._zinc_utils = ZincUtils(context=context,
                                 nailgun_task=self,
                                 jvm_options = self._jvm_options,
                                 color=color,
                                 jvm_tool_bootstrapper=self._jvm_tool_bootstrapper)

    # If we are compiling scala libraries with circular deps on java libraries we need to
    # make sure those cycle deps are present.
    for scala_target in self.context.targets(lambda t: isinstance(t, ScalaLibrary)):
      for java_target in scala_target.java_sources:
        self.context.add_target(java_target)

  def create_analysis_tools(self):
    return AnalysisTools(self.context, ZincAnalysisParser(self._classes_dir), ZincAnalysis)

  def extra_classpath_elements(self):
    # Classpath entries necessary for our compiler plugins.
    return self._zinc_utils.plugin_jars()

  def extra_products(self, target):
      ret = []
      if target.is_scalac_plugin and target.classname:
        root, plugin_info_file = ZincUtils.write_plugin_info(self._resources_dir, target)
        ret.append((root, [plugin_info_file]))
      return ret

  def compile(self, args, classpath, sources, classes_output_dir, analysis_file):
    # We have to treat our output dir as an upstream element, so zinc can find valid
    # analysis for previous partitions. We use the global valid analysis for the upstream.
    upstream = { classes_output_dir: self._analysis_file } if os.path.exists(self._analysis_file) else {}
    return self._zinc_utils.compile(args, classpath + [self._classes_dir], sources,
                                    classes_output_dir, analysis_file, upstream)
