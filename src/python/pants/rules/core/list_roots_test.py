# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json

from pants.rules.core import list_roots
from pants_test.console_rule_test_base import ConsoleRuleTestBase


class RootsTest(ConsoleRuleTestBase):
  goal_cls = list_roots.Roots

  @classmethod
  def rules(cls):
    return super().rules() + list_roots.rules()

  def test_no_langs(self):
    source_roots = json.dumps({'fakeroot': tuple()})
    self.create_dir('fakeroot')
    self.assert_console_output('fakeroot: *',
      args=[f"--source-source-roots={source_roots}"]
    )

  def test_single_source_root(self):
    source_roots = json.dumps({'fakeroot': ('lang1', 'lang2')})
    self.create_dir('fakeroot')
    self.assert_console_output('fakeroot: lang1,lang2',
        args=[f"--source-source-roots={source_roots}"]
    )

  def test_multiple_source_roots(self):
    source_roots = json.dumps({
      'fakerootA': ('lang1',),
      'fakerootB': ('lang2',)
    })
    self.create_dir('fakerootA')
    self.create_dir('fakerootB')
    self.assert_console_output('fakerootA: lang1', 'fakerootB: lang2',
      args=[f"--source-source-roots={source_roots}"]
    )
