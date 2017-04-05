# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from contextlib import contextmanager
from textwrap import dedent

from pants.util.dirutil import safe_open
from pants_test.pants_run_integration_test import PantsRunIntegrationTest
from pants_test.testutils.file_test_util import exact_files


class JaxWsGenTest(PantsRunIntegrationTest):

  @classmethod
  def hermetic(cls):
    return True

  def setUp(self):
    super(JaxWsGenTest, self).setUp()
    self.full_config = {
      'GLOBAL': {
        'pythonpath': ["%(buildroot)s/contrib/jax_ws/src/python"],
        'backend_packages': ["pants.backend.codegen", "pants.backend.jvm", "pants.contrib.jax_ws"]
      },
      'gen.jax-ws' : {
        'jvm_options': ['-Djavax.xml.accessExternalSchema=all']
      }
    }

  @staticmethod
  def jax_ws_test_target(name):
    return 'contrib/jax_ws/tests/wsdl/org/pantsbuild/contrib/jax_ws:' + name

  def test_hello_service(self):
    with self.temporary_workdir() as workdir:
      cmd = ['gen', self.jax_ws_test_target('hello-service')]
      pants_run = self.run_pants_with_workdir(cmd, workdir, config=self.full_config)
      self.assert_success(pants_run)
      self.assertIn('[jax-ws]', pants_run.stdout_data)

      jax_ws_contents = [p for p in os.listdir(os.path.join(workdir, 'gen', 'jax-ws'))
                         if p != 'current']
      self.assertEqual(len(jax_ws_contents), 1)
      hash_dir = jax_ws_contents[0]

      root = os.path.join(workdir, 'gen', 'jax-ws', hash_dir,
                          'contrib.jax_ws.tests.wsdl.org.pantsbuild.contrib.jax_ws.hello-service',
                          'current')

      self.assertEquals(sorted(['com/example/HelloWorldServer.java',
                                'com/example/HelloWorldServerImplService.java']),
                        sorted(exact_files(root)))

  def test_invalid_service(self):
    with self._create_invalid_jax_ws_project() as srcdir:
      cmd = ['gen', os.path.join(srcdir, 'src/jax_ws/test:invalid-service')]
      pants_run = self.run_pants(cmd, config=self.full_config)
      self.assert_failure(pants_run)
      self.assertIn('[jax-ws]', pants_run.stdout_data)
      self.assertIn('[ERROR] wsdl:binding', pants_run.stdout_data)

  @contextmanager
  def _create_invalid_jax_ws_project(self):
    with self.temporary_sourcedir() as srcdir:
      with safe_open(os.path.join(srcdir, 'src/jax_ws/test/InvalidService.wsdl'), 'w') as fp:
        fp.write(dedent("""
            <definitions xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"
                xmlns:wsp="http://www.w3.org/ns/ws-policy"
                xmlns:wsp1_2="http://schemas.xmlsoap.org/ws/2004/09/policy"
                xmlns:wsam="http://www.w3.org/2007/05/addressing/metadata"
                xmlns:soap="http://schemas.xmlsoap.org/wsdl/soap/"
                xmlns:tns="http://example.com/"
                xmlns:xsd="http://www.w3.org/2001/XMLSchema"
                xmlns="http://schemas.xmlsoap.org/wsdl/"
                targetNamespace="http://example.com/"
                name="InvalidServerImplService">
              <types/>
              <service name="InvalidServerImplService">
                <port name="InvalidServerImplPort" binding="tns:InvalidServerImplPortBinding">
                  <soap:address location="http://127.0.0.1:9876/invalid"/>
                </port>
              </service>
            </definitions>
            """).strip())
      with safe_open(os.path.join(srcdir, 'src/jax_ws/test/BUILD'), 'w') as fp:
        fp.write(dedent("""
            jax_ws_library(name='invalid-service',
              sources = [
                'InvalidService.wsdl',
              ],
              dependencies = [],
            )
            """).strip())
      yield srcdir
