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
    print ("genlang going going")

  #TODO:Investigate.Each invocation of aapt creates a package, I don't think it can batch for each aapt binary used
    # somewhere in an aapt class we will need to handle "crunch" command for release builds.
    for target in targets:
      if lang != 'java':
        raise TaskError('Unrecognized android gen lang: %s' % lang)
      output_dir = safe_mkdir(self._aapt_out(target))
      # instead of ignore assets, we could move the BUILD dict up a level. May need it later anyway.
      ignored_assets='!.svn:!.git:!.ds_store:!*.scc:.*:<dir>_*:!CVS:!thumbs.db:!picasa.ini:!*~:BUILD*'
      args = [self.aapt_tool(target), 'package', '-m',  '-J', output_dir, '-M', target.manifest,
              '-S', target.resources, "-I", self.android_jar_tool(target),
              '--ignore-assets', ignored_assets]
      log.debug('Executing: %s' % ' '.join(args))
      process = subprocess.Popen(args)
      result = process.wait()
      if result != 0:
        raise TaskError('Android %s ... exited non-zero (%i)' % (self.aapt_tool(target), result))


  def createtarget(self, lang, gentarget, dependees):
    """from: CodeGen: aapt class must override and create a synthetic target.
    The target must contain the sources generated for the given gentarget.
    """
    print ("aapt createtarget")
    #This method creates the new target to replace the acted upon resources in the target graph
    # create the path and sources
    aapt_gen_file = os.path.join(gentarget.target_base, self._aapt_out(gentarget), gentarget.package, 'R.java')
    #Use the address to create a syntheticTarget address
    address = SyntheticAddress.parse(spec_path=aapt_gen_file, target_name = gentarget.id)
    # create new JavaLibraryTarget
    tgt = self.context.add_new_target(address,
                                      JavaLibrary,
                                      name=gentarget.id,
                                      #TODO:are sources full path? Address seem to be
                                      sources=aapt_gen_file,
                                      provides=gentarget.provides,
                                      dependencies=[],
                                      excludes=gentarget.excludes)
    # update (or inject?) deps
    for dependee in dependees:
      dependee.update_dependencies([tgt])
    return tgt

  def package_path(self, target):
    #TODO test this
    #needs to convert the package name (com.foo.bar) into a package path (com/foo/bar)
    return target.package.replace('.', os.sep)


  def _aapt_out(self, target):
    return os.path.join(target.target_base, 'bin')

  # resolve the tools on a per-target basis
  def aapt_tool(self, target):
    return os.path.join(self._dist._sdk_path, ('build-tools/' + target.build_tools_version), 'aapt')

  def android_jar_tool(self, target):
    return os.path.join(self._dist._sdk_path, 'platforms', ('android-' + target.target_sdk_version), 'android.jar')


  #todo (mateor): debate merits of AaptClassMixin class