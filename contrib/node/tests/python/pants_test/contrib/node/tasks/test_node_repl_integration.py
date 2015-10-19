# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class NodeReplIntegrationTest(PantsRunIntegrationTest):

  def test_run_repl(self):
    command = ['-q',
               'repl',
               'contrib/node/examples/src/node/web-component-button']
    program = dedent("""
        var React = require('react');
        var HelloWorldClass = React.createClass({
          render: function() {
            return React.createElement("div", null, "Hello World");
          }
        });
        console.log(React.renderToStaticMarkup(React.createElement(HelloWorldClass)));
      """)
    pants_run = self.run_pants(command=command, stdin_data=program)

    self.assert_success(pants_run)
    self.assertEqual('<div>Hello World</div>', pants_run.stdout_data.strip())

  def test_run_repl_passthrough(self):
    eval_string = (
      'var React = require("react");'
      'console.log(React.renderToStaticMarkup(React.createElement("div", null, "Hello World")));'
    )
    command = ['-q',
               'repl',
               'contrib/node/examples/src/node/web-component-button',
               '--',
               '--eval',
               eval_string]
    pants_run = self.run_pants(command=command)

    self.assert_success(pants_run)
    self.assertEqual('<div>Hello World</div>', pants_run.stdout_data.strip())
