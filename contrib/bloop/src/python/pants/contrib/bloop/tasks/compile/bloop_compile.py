# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import json
import os
import time

from google.protobuf.json_format import MessageToJson
from google.protobuf.json_format import Parse as JsonToMessage
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.java.jar.jar_dependency import JarDependency
from pants.util.process_handler import subprocess


class BloopCompile(NailgunTask):

  @classmethod
  def register_options(cls, register):
    super(BloopCompile, cls).register_options(register)

    cls.register_jvm_tool(
      register,
      'bloop-launcher',
      classpath=[
        JarDependency(
          org='ch.epfl.scala',
          name='bloop-launcher_2.12',
          rev='1.3.2',
        ),
      ],
    )

  @classmethod
  def prepare(cls, options, round_manager):
    super(BloopCompile, cls).prepare(options, round_manager)
    round_manager.require_data('bloop_output_dir')

  _supported_languages = ['java', 'scala']

  def _initialize_build_request(self):
    bloop_output_dir = self.context.products.get_data('bloop_output_dir')
    return InitializeBuildParams(
      # displayName='pants-bloop-bsp-compile',
      # version='???',
      # bspVersion='2.0',
      # Tell bloop where the project is located!
      rootUri='file://{}'.format(os.path.dirname(bloop_output_dir)),
      capabilities=BuildClientCapabilities(languageIds=self._supported_languages),
      # No extra metadata for now!
      # data=None,
    )

  def execute(self):
    return

    bsp_launcher_process = self.runjava(
      classpath=self.tool_classpath('bloop-launcher'),
      main='bloop.launcher.Launcher',
      jvm_options=[],
      # NB: jvm options need to be prefixed with -J (TODO: does this work for jvm properties?)!!!
      args=[
        '-J{}'.format(opt) for opt in self.get_options().jvm_options
      ] + [
        # TODO: match this with the launcher bloop version and the bloop config version somehow???
        '1.3.2',
      ],
      workunit_name='bloop-compile',
      workunit_labels=[WorkUnitLabel.COMPILER],
      do_async=True,
      stdin=subprocess.PIPE,
      stdout=subprocess.PIPE)

    # Implement the BSP client protocol over stdin/stdout: see
    # https://github.com/scalacenter/bsp/tree/master/docs/bsp.md!
    def write_json_rpc_message(message):
      json_message = MessageToJson(message)
      json_rpc_message = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "build/initialize",
        "params": json.loads(json_message),
      }
      json_rpc_content = json.dumps(json_rpc_message).encode('utf-8')
      json_rpc_header = "Content-Length: {}\r\n\r\n".format(len(json_rpc_content)).encode('ascii')
      json_rpc_with_header = json_rpc_header + json_rpc_content
      # TODO: is the stdin automatically line-buffered, or do we need to call .flush()?
      bsp_launcher_process.stdin.write('{}\n'.format(json_rpc_with_header))
      bsp_launcher_process.stdin.flush()
      self.context.log.info('written: {}'.format(json_rpc_with_header))
    def read_json_rpc_message(base_message):
      json_rpc_header = ''
      while len(json_rpc_header) == 0:
        json_rpc_header = bsp_launcher_process.stdout.readline()
      self.context.log.info('read: {}').format(json_rpc_header)
      raise Exception('huh: {}'.format(bsp_launcher_process.stdout.readline()))
      return JsonToMessage(json_message, base_message)

    # Send the initialize request!
    time.sleep(5)

    write_json_rpc_message(self._initialize_build_request())

    initialize_result = read_json_rpc_message(InitializeBuildResult())
    supported_compile_languages = initialize_result.capabilities.compileProvider.languageIds
    if not set(self._supported_languages).issubset(set(supported_compile_languages)):
      raise TaskError("bsp server {} does not support required languages for compile {}! Was: {}."
                      .format(initialize_result.displayName,
                              self._supported_languages,
                              supported_compile_languages))
    self.context.log.info("Connected to bsp server {} at version {}, using bsp version {}!"
                          .format(initialize_result.displayName,
                                  initialize_result.version,
                                  initialize_result.bspVersion))

    bsp_launcher_process.terminate()

    # TODO: `build/shutdown` or `build/exit` at the end??

    # TODO: speak bsp to it and tell it where to locate everything / etc!
