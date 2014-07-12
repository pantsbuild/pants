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
  There may be an aapt superclass or mixin, as aapt binary has future packaging functions besides codegen.

  aapt supports 6 major commands: {dump, list, add, remove, crunch, package}
  For right now, pants is only supporting 'package'. More to come as we support Release builds (crunch, at minimum).

  Commands and flags for aapt can be seen here:
  https://android.googlesource.com/platform/frameworks/base/+/master/tools/aapt/Command.cpp
  """

  def __init__(self, context, workdir):
    #define the params needed in the BUILD file {name, sources, dependencies, etc.}
    super(AaptGen, self).__init__(context, workdir)
    lang = 'java'
    self.gen_langs=set()
    self.gen_langs.add(lang)
    self.dist = self._dist

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
      print ("output_dir is %s" % output_dir)
      manifest = os.path.join(target.manifest)
      print (manifest)
      # BUILD files in the resource folder chokes aapt. This is a defensive measure.
      ignored_assets='!.svn:!.git:!.ds_store:!*.scc:.*:<dir>_*:!CVS:!thumbs.db:!picasa.ini:!*~:BUILD*'
      args = [self.aapt_tool(target), 'package', '-m',  '-J', output_dir, '-M', manifest,
              '-S', target.resource_dir, "-I", self.android_jar_tool(target),
              '--ignore-assets', ignored_assets]
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
    # This is going in the wrong dir, one above where it is wanted.
    return os.path.join(target.address.spec_path, 'bin')

  # resolve the tools on a per-target basis
  def aapt_tool(self, target):
    aapt = self.dist.aapt_tool(target.build_tools_version)
    print ("aapt_tool: %s" % aapt)
    # this only works because there is a default build_tools_version. How to get this info?
    # I guess two options only: add it to BUILD file or parse the manifest already.
    return aapt

  def android_jar_tool(self, target):

    #return os.path.join(self._dist._sdk_path, 'platforms', ('android-' + target.target_sdk), 'android.jar')
    android_jar = self.dist.android_jar_tool(target.target_sdk)
    print ("android_jar_tool: %s" % android_jar)
    return android_jar
  #todo (mateor): debate merits of AaptClassMixin class