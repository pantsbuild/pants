# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import subprocess

from twitter.common import log
from twitter.common.dirutil import safe_mkdir

from pants.backend.android.targets.android_resources import AndroidResources
from pants.backend.android.tasks.android_task import AndroidTask
from pants.backend.codegen.tasks.code_gen import CodeGen
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.base.address import SyntheticAddress
from pants.base.exceptions import TaskError


class AaptGen(AndroidTask, CodeGen):
  """
  CodeGen for Android app building with the Android Asset Packaging Tool.
  There may be an aapt superclass or mixin, as aapt binary has future packaging functions
  besides codegen.

  aapt supports 6 major commands: {dump, list, add, remove, crunch, package}
  For right now, pants is only supporting 'package'. More to come as we support Release builds
  (crunch, at minimum).

  Commands and flags for aapt can be seen here:
  https://android.googlesource.com/platform/frameworks/base/+/master/tools/aapt/Command.cpp
  """
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    super(AaptGen, cls).setup_parser(option_group, args, mkflag)

    option_group.add_option(mkflag("target-sdk"), dest="target_sdk",
                            help="[%default] Specifies the target Android SDK. "
                                 "Overrides AndroidManifest.xml.")

    option_group.add_option(mkflag("build-tools-version"), dest="build_tools_version",
                            help="[%default] Specifies the Android build-tools version with which "
                                 "to compile the target.")

  def __init__(self, context, workdir):
    #define the params needed in the BUILD file {name, sources, dependencies, etc.}
    super(AaptGen, self).__init__(context, workdir)
    lang = 'java'
    self.gen_langs=set()
    self.gen_langs.add(lang)
    self.dist = self._dist
    self.forced_target_sdk = context.options.target_sdk
    self.forced_build_tools_version = context.options.build_tools_version


  def is_gentarget(self, target):
    return isinstance(target, AndroidResources)

  def genlangs(self):
    return dict(java=lambda t: t.is_jvm)

  def is_forced(self, lang):
    return lang in self.gen_langs

  def genlang(self, lang, targets):
    """aapt must override and generate code in :lang for the given targets.

    May return a list of pairs (target, files) where files is a list of files
    to be cached against the target.
    """
    print ("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")

    # somewhere in an aapt class we will need to handle "crunch" command for release builds.
    for target in targets:
      if lang != 'java':
        raise TaskError('Unrecognized android gen lang: %s' % lang)
      output_dir = self._aapt_out(target)
      safe_mkdir(output_dir)
      args = []

      if self.forced_build_tools_version:
        args.append(self.aapt_tool(self.forced_build_tools_version))
      else:
        args.append(self.aapt_tool(target.build_tools_version))

      args.extend(['package', '-m', '-J', output_dir, '-M', target.manifest,
               '-S', target.resource_dir, '-I'])
      print ("self.forced_target_sdk is %s" % self.forced_target_sdk)
      if self.forced_target_sdk:
        args.append(self.android_jar_tool(self.forced_target_sdk))
      else:
        args.append(self.android_jar_tool(target.target_sdk))
      print ("output_dir is %s" % output_dir)
      #manifest = os.path.join(target.manifest)
      # BUILD files in the resource folder chokes aapt. This is a defensive measure.
      ignored_assets='!.svn:!.git:!.ds_store:!*.scc:.*:<dir>_*:!CVS:!thumbs.db:!picasa.ini:!*~:BUILD*'
      args.extend(['--ignore-assets', ignored_assets])
      print ("args are %s" % args)
      log.debug('Executing: %s' % ' '.join(args))
      process = subprocess.Popen(args)
      result = process.wait()
      # TODO(mateor) refine/check this error catch
      if result != 0:
        raise TaskError('Android %s ... exited non-zero (%i)' % (self.aapt_tool(target), result))


  def createtarget(self, lang, gentarget, dependees):
    """from: CodeGen: aapt class must override and create a synthetic target.
    The target must contain the sources generated for the given gentarget.
    """
    print ("aapt createtarget")
    #This method creates the new target to replace the acted upon resources in the target graph
    # create the path and sources
    aapt_gen_file = os.path.join(self._aapt_out(gentarget), self.package_path(gentarget.package))
    print ("AAPT_GEN_FILE: %s" % aapt_gen_file)
    #Use the address to create a syntheticTarget address
    address = SyntheticAddress(spec_path=aapt_gen_file, target_name = gentarget.id)
    # create new JavaLibraryTarget
    print (gentarget.id, gentarget)
    tgt = self.context.add_new_target(address,
                                      JavaLibrary,
                                      derived_from=gentarget,
                                      #TODO:are sources full path? Address seem to be
                                      sources=['R.java'],
                                      #provides=gentarget.provides,
                                      dependencies=[])
                                      # excludes=gentarget.excludes)
    # update (or inject?) deps
    #print (dependees)
    print ("TARGET_ADDDRESS: %s" % tgt.address)
    for dependee in dependees:
      dependee.inject_dependency(tgt.address)
    return tgt

  def package_path(self, package):
    #TODO test this
    #needs to convert the package name (com.foo.bar) into a package path (com/foo/bar)
    return package.replace('.', os.sep)


  def _aapt_out(self, target):
    return os.path.join(target.address.spec_path, 'bin')

  # resolve the tools on a per-target basis
  def aapt_tool(self, build_tools_version):
    """This fetches the appropriate aapt tool.
    The build_tools_version argument is a string(e.g. "19.1.")."""
    aapt = self.dist.aapt_tool(build_tools_version)
    print ("aapt_tool: %s" % aapt)
    return aapt

  def android_jar_tool(self, target_sdk):
    """This fetches the appropriate android.jar. The target_sdk argument is a string (e.g. "18")."""
    android_jar = self.dist.android_jar_tool(target_sdk)
    print ("android_jar_tool: %s" % android_jar)
    return android_jar
  #todo (mateor): debate merits of AaptClassMixin class

  # .aar library files output R.txt with a flag of '--output-text-symbols