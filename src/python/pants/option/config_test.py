# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent
from typing import Dict

from twitter.common.collections import OrderedSet

from pants.option.config import Config
from pants.testutil.test_base import TestBase
from pants.util.contextutil import temporary_file


class ConfigTest(TestBase):

  def _setup_config(self, config1_content: str, config2_content: str, *, suffix: str) -> Config:
    with temporary_file(binary_mode=False, suffix=suffix) as config1, \
      temporary_file(binary_mode=False, suffix=suffix) as config2:
      config1.write(config1_content)
      config1.close()
      config2.write(config2_content)
      config2.close()
      parsed_config = Config.load(
        config_paths=[config1.name, config2.name], seed_values={"buildroot": self.build_root}
      )
      assert [config1.name, config2.name] == parsed_config.sources()
    return parsed_config

  def setUp(self) -> None:
    ini1_content = dedent(
      """
      [DEFAULT]
      name: foo
      answer: 42
      scale: 1.2
      path: /a/b/%(answer)s
      embed: %(path)s::foo
      disclaimer:
        Let it be known
        that.

      [a]
      list: [1, 2, 3, %(answer)s]
      list2: +[7, 8, 9]

      [b]
      preempt: True
      
      [b.nested]
      dict: {
          'a': 1,
          'b': %(answer)s,
          'c': ['%(answer)s', '%(answer)s'],
        }
      
      [b.nested.nested-again]
      movie: inception
      """
    )
    ini2_content = dedent(
      """
      [a]
      fast: True

      [b]
      preempt: False
      
      [c.child]
      no_values_in_parent: True

      [defined_section]
      """
    )
    self.config = self._setup_config(ini1_content, ini2_content, suffix=".ini")
    self.default_seed_values = Config._determine_seed_values(
      seed_values={"buildroot": self.build_root},
    )
    self.default_file1_values = {
      "name": "foo",
      "answer": "42",
      "scale": "1.2",
      "path": "/a/b/42",
      "embed": "/a/b/42::foo",
      "disclaimer": "\nLet it be known\nthat.",
    }
    self.expected_file1_options = {
      "a": {
        "list": "[1, 2, 3, 42]",
        "list2": "+[7, 8, 9]",
      },
      "b": {
        "preempt": "True",
      },
      "b.nested": {
        "dict": "{\n'a': 1,\n'b': 42,\n'c': ['42', '42'],\n}"
      },
      "b.nested.nested-again": {
        "movie": "inception",
      },
    }
    self.expected_file2_options: Dict[str, Dict[str, str]] = {
      "a": {
        "fast": "True",
      },
      "b": {
        "preempt": "False",
      },
      "c.child": {
        "no_values_in_parent": "True",
      },
      "defined_section": {},
    }
    self.expected_combined_values: Dict[str, Dict[str, str]] = {
      **self.expected_file1_options,
      **self.expected_file2_options,
      "a": {
        **self.expected_file2_options["a"], **self.expected_file1_options["a"],
      },
    }

  def test_sections(self) -> None:
    expected_sections = list(
      OrderedSet([*self.expected_file2_options.keys(), *self.expected_file1_options.keys()])
    )
    assert self.config.sections() == expected_sections
    for section in expected_sections:
      assert self.config.has_section(section) is True
    # We should only look at explicitly defined sections. For example, if `cache.java` is defined
    # but `cache` is not, then `cache` should not be included in the sections.
    assert self.config.has_section('c') is False

  def test_has_option(self) -> None:
    # Check has all DEFAULT values
    for default_option in (*self.default_seed_values.keys(), *self.default_file1_values.keys()):
      assert self.config.has_option(section="DEFAULT", option=default_option) is True
    # Check every explicitly defined section has its options + the seed defaults
    for section, options in self.expected_combined_values.items():
      for option in (*options, *self.default_seed_values):
        assert self.config.has_option(section=section, option=option) is True
    # Check every section for file1 also has file1's DEFAULT values
    for section in self.expected_file1_options:
      for option in self.default_file1_values:
        assert self.config.has_option(section=section, option=option) is True
    # Check that file1's DEFAULT values don't apply to sections only defined in file2
    sections_only_in_file2 = set(self.expected_file2_options.keys()) - set(
      self.expected_file1_options.keys()
    )
    for section in sections_only_in_file2:
      for option in self.default_file1_values:
        assert self.config.has_option(section=section, option=option) is False
    # Check that non-existent options are False
    nonexistent_options = {
      "DEFAULT": "fake",
      "a": "fake",
      "b": "fast",
    }
    for section, option in nonexistent_options.items():
      assert self.config.has_option(section=section, option=option) is False

  def test_list_all_options(self) -> None:
    # This is used in `options_bootstrapper.py` to validate that every option is recognized.
    file1_config = self.config.configs()[1]
    file2_config = self.config.configs()[0]
    for section, options in self.expected_file1_options.items():
      assert file1_config.values.options(section=section) == [
        *options.keys(), *self.default_seed_values.keys(), *self.default_file1_values.keys(),
      ]
    for section, options in self.expected_file2_options.items():
      assert file2_config.values.options(section=section) == [
        *options.keys(), *self.default_seed_values.keys()]

  def test_default_values(self) -> None:
    # This is used in `options_bootstrapper.py` to ignore default values when validating options.
    file1_config = self.config.configs()[1]
    file2_config = self.config.configs()[0]
    # NB: string interpolation should only happen when calling _ConfigValues.get_value(). The
    # values for _ConfigValues.defaults() are not yet interpolated.
    default_file1_values_unexpanded = {
      **self.default_file1_values, "path": "/a/b/%(answer)s", "embed": "%(path)s::foo",
    }
    assert file1_config.values.defaults() == {
      **self.default_seed_values, **default_file1_values_unexpanded,
    }
    assert file2_config.values.defaults() == self.default_seed_values

  def test_get(self) -> None:
    # Check the DEFAULT section
    for option, value in {**self.default_seed_values, **self.default_file1_values}.items():
      assert self.config.get(section="DEFAULT", option=option) == value
    # Check the combined values, including that each section has the default seed values
    for section, section_values in self.expected_combined_values.items():
      for option, value in {**section_values, **self.default_seed_values}.items():
        assert self.config.get(section=section, option=option) == value
    # Check that each section from file1 also has file1's default values
    for section in self.expected_file1_options:
      for option, value in self.default_file1_values.items():
        assert self.config.get(section=section, option=option) == value

    def check_defaults(default: str) -> None:
      assert self.config.get(section='c', option='fast') is None
      assert self.config.get(section='c', option='preempt', default=None) is None
      assert self.config.get(section='c', option='jake', default=default) == default

    check_defaults('')
    check_defaults('42')

  def test_empty(self) -> None:
    config = Config.load([])
    assert config.sections() == []
    assert config.sources() == []
    assert config.has_section("DEFAULT") is False
    assert config.has_option(section="DEFAULT", option="name") is False
