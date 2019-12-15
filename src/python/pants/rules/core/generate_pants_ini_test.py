# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import configparser
from pathlib import Path

from pants.rules.core.generate_pants_ini import GeneratePantsIni
from pants.rules.core.generate_pants_ini import rules as generate_pants_ini_rules
from pants.testutil.console_rule_test_base import ConsoleRuleTestBase
from pants.version import VERSION


class GeneratePantsIniTest(ConsoleRuleTestBase):

  goal_cls = GeneratePantsIni

  @classmethod
  def rules(cls):
    return (*super().rules(), *generate_pants_ini_rules())

  def test_fails_if_file_already_exists(self) -> None:
    Path(self.build_root, "pants.ini").touch()
    self.execute_rule(exit_code=1)

  def test_generates_file(self) -> None:
    self.execute_rule()
    pants_ini = Path(self.build_root, "pants.ini")
    assert pants_ini.exists()
    config = configparser.ConfigParser()
    config.read(pants_ini)
    assert config["GLOBAL"]["pants_version"] == VERSION
