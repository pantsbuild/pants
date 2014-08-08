# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import subprocess

from twitter.common import log

from pants.backend.android.targets.android_binary import AndroidBinary
from pants.backend.android.targets.android_target import AndroidTarget
from pants.backend.android.tasks.aapt_task import AaptTask
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit
from pants.util.dirutil import safe_mkdir

class AaptBuilder(AaptTask):


  @classmethod
  def product_types(cls):
    return ['apk']

  @staticmethod
  def is_app(target):
    return isinstance(target, AndroidBinary)

  @staticmethod
  def is_android(target):
    return isinstance(target, AndroidTarget)

  def __init__(self, context, workdir):
    super(AaptBuilder, self).__init__(context, workdir)

  def prepare(self, round_manager):
    round_manager.require_data('java')
    round_manager.require_data('dex')

  def render_args(self, target, resource_dir, inputs):
    args = []

    if self._forced_build_tools_version:
      args.append(self.aapt_tool(self._forced_build_tools_version))
    else:
      args.append(self.aapt_tool(target.build_tools_version))

    #TODO (MATEOR) update for this subclass
    # Glossary of used aapt flags. Aapt handles a ton of action, this will continue to expand.
    #   : 'package' is the main aapt operation (see class docstring for more info).
    #   : '-m' is to "make" a package directory under location '-J'.
    #   : '-J' Points to the output directory.
    #   : '-M' is the AndroidManifest.xml of the project.
    #   : '-S' points to the resource_dir to "spider" down while collecting resources.
    #   : '-I' packages to add to base "include" set, here it is the android.jar of the target-sdk.

    args.extend(['package', '-v', '-f', '-M', target.manifest,
                 '-S'])

    args.extend(resource_dir)
    if self._forced_target_sdk:
      args.extend(['-I', self.android_jar_tool(self._forced_target_sdk)])
    else:
      args.extend(['-I', self.android_jar_tool(target.target_sdk)])

    if self._forced_ignored_assets:
      args.extend(['--ignore-assets', self._forced_ignored_assets])
    else:
      args.extend(['--ignore-assets', self.IGNORED_ASSETS])

    # extend -F bin/*apk $INPUT_DIRS
    args.extend(['-F', os.path.join(self.workdir, target.name + '.apk')])
    args.extend(inputs)
    log.debug('Executing: {0}'.format(args))
    print (args)
    for arg in args:
      print("arg {0} is: {1}".format(arg, type(arg)))
    return args

  def execute(self):
    safe_mkdir(self.workdir)
    with self.context.new_workunit(name='apk-bundle', labels=[WorkUnit.MULTITOOL]):  #TODO Check Label
      targets = self.context.targets(self.is_app)
      #TODO (MATEOR) invalidation machinery
      for target in targets:
        input_dirs = []
        resource_dir = []
        mapping = self.context.products.get('dex')
        for basedir in mapping.get(target):
          input_dirs.append(basedir)


        def add_r_java(target):
          new_resources = self.context.products.get('android-gen')
          if new_resources.get(target) is not None:
            resource_dir.append(os.path.join(get_buildroot(), target.resource_dir))
            print(resource_dir)
            print("Donald DUUUCKCKCKCKCKCKCK")
            for basedir in new_resources.get(target):
              input_dirs.append(os.path.join(basedir, self.package_path(target.package)))

        target.walk(add_r_java)
        print(type(resource_dir))
        process = subprocess.Popen(self.render_args(target, resource_dir, input_dirs))
        result = process.wait()
        if result != 0:
          raise TaskError('Android aapt tool exited non-zero ({code})'.format(code=result))

        [u'/Users/mateor/development/android-sdk-macosx/build-tools/19.1.0/aapt', u'package', u'-v', u'-f', u'-M', u'src/android/example/AndroidManifest.xml', u'-S', None, u'-I', u'/Users/mateor/development/android-sdk-macosx/platforms/android-19/android.jar', u'--ignore-assets', '!.svn:!.git:!.ds_store:!*.scc:.*:<dir>_*:!CVS:!thumbs.db:!picasa.ini:!*~:BUILD*', u'-F', u'/Users/mateor/development/pants/.pants.d/bundle/apk', u'/Users/mateor/development/pants/.pants.d/dex/dex/src.android.example.hello', u'/Users/mateor/development/pants/.pants.d/gen/aapt/com/pants/examples/hello']