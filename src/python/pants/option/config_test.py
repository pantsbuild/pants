# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest
from dataclasses import dataclass
from textwrap import dedent
from typing import Dict

from pants.engine.fs import FileContent
from pants.option.config import Config, TomlSerializer


@dataclass(frozen=True)
class ConfigFile:
    content: str
    default_values: Dict
    expected_options: Dict


FILE_1 = ConfigFile(
    content=dedent(
        """
        [DEFAULT]
        name = "%(env.NAME)s"
        answer = 42
        scale = 1.2
        path = "/a/b/%(answer)s"
        embed = "%(path)s::%(name)s"
        disclaimer = '''
        Let it be known
        that.'''

        [a]
        # TODO: once TOML releases its new version with support for heterogenous lists, we should be
        # able to rewrite this to `[1, 2, 3, "%(answer)s"`. See
        # https://github.com/toml-lang/toml/issues/665.
        list = ["1", "2", "3", "%(answer)s"]
        list2.add = [7, 8, 9]
        list3.remove = ["x", "y", "z"]

        [b]
        preempt = true

        [c]
        name = "overridden_from_default"
        interpolated_from_section = "%(name)s is interpolated"
        recursively_interpolated_from_section = "%(interpolated_from_section)s (again)"

        [d.dict_val]
        # Make sure we don't misinterpret `add` and `remove` as list options.
        add = 0
        remove = 0
        nested = { nested_key = 'foo' }

        [list_merging]
        list1 = []
        list2 = [1, 2]
        list3.add = [3, 4]
        list4.remove = [5]
        list5 = [6, 7]
        """
    ),
    default_values={
        "name": "foo",
        "answer": 42,
        "scale": 1.2,
        "path": "/a/b/42",
        "embed": "/a/b/42::foo",
        "disclaimer": "Let it be known\nthat.",
    },
    expected_options={
        "a": {"list": '["1", "2", "3", "42"]', "list2": "+[7, 8, 9]", "list3": '-["x", "y", "z"]'},
        "b": {"preempt": "True"},
        "c": {
            "name": "overridden_from_default",
            "interpolated_from_section": "overridden_from_default is interpolated",
            "recursively_interpolated_from_section": "overridden_from_default is interpolated (again)",
        },
        "d": {"dict_val": "{'add': 0, 'remove': 0, 'nested': {'nested_key': 'foo'}"},
        "list_merging": {
            "list1": "[]",
            "list2": "[1, 2]",
            "list3": "+[3, 4]",
            "list4": "-[5]",
            "list5": "[6, 7]",
        },
    },
)


FILE_2 = ConfigFile(
    content=dedent(
        """
        [a]
        fast = true

        [b]
        preempt = false

        [d]
        list.add = [0, 1]
        list.remove = [8, 9]

        [empty_section]

        [list_merging]
        list1 = [11, 22]
        list2.add = [33]
        list3.add = [8, 9]
        list3.remove = [4, 55]
        list4 = [66]
        list6.add = [77, 88]
        """
    ),
    default_values={},
    expected_options={
        "a": {"fast": "True"},
        "b": {"preempt": "False"},
        "d": {"list": "+[0, 1],-[8, 9]"},
        "empty_section": {},
        "list_merging": {
            "list1": "[11, 22]",
            "list2": "+[33]",
            "list3": "+[8, 9],-[4, 55]",
            "list4": "[66]",
            "list6": "+[77, 88]",
        },
    },
)


def _setup_config() -> Config:
    parsed_config = Config.load(
        file_contents=[
            FileContent("file1.toml", FILE_1.content.encode()),
            FileContent("file2.toml", FILE_2.content.encode()),
        ],
        seed_values={"buildroot": "fake_buildroot"},
        env={"NAME": "foo"},
    )
    assert ["file1.toml", "file2.toml"] == parsed_config.sources()
    return parsed_config


class ConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = _setup_config()
        self.default_seed_values = Config._determine_seed_values(
            seed_values={"buildroot": "fake_buildroot"},
            env={"NAME": "foo"},
        )
        self.expected_combined_values: dict[str, dict[str, list[str]]] = {
            "a": {
                "list": ['["1", "2", "3", "42"]'],
                "list2": ["+[7, 8, 9]"],
                "list3": ['-["x", "y", "z"]'],
                "fast": ["True"],
            },
            "b": {"preempt": ["True", "False"]},
            "c": {
                "name": ["overridden_from_default"],
                "interpolated_from_section": ["overridden_from_default is interpolated"],
                "recursively_interpolated_from_section": [
                    "overridden_from_default is interpolated (again)"
                ],
            },
            "d": {
                "dict_val": ["{'add': 0, 'remove': 0, 'nested': {'nested_key': 'foo'}}"],
                "list": ["+[0, 1],-[8, 9]"],
            },
            "empty_section": {},
            "list_merging": {
                "list1": ["[]", "[11, 22]"],
                "list2": ["[1, 2]", "+[33]"],
                "list3": ["+[3, 4]", "+[8, 9],-[4, 55]"],
                "list4": ["-[5]", "[66]"],
                "list5": ["[6, 7]"],
                "list6": ["+[77, 88]"],
            },
        }

    def test_default_values(self) -> None:
        # This is used in `options_bootstrapper.py` to ignore default values when validating options.
        file1_values = self.config.values[0]
        file2_values = self.config.values[1]
        # NB: string interpolation should only happen when calling _ConfigValues.get_value(). The
        # values for _ConfigValues.defaults are not yet interpolated.
        default_file1_values_unexpanded = {
            **FILE_1.default_values,
            "name": "%(env.NAME)s",
            "path": "/a/b/%(answer)s",
            "embed": "%(path)s::%(name)s",
        }
        assert file1_values.defaults == {
            **self.default_seed_values,
            **default_file1_values_unexpanded,
        }
        assert file2_values.defaults == self.default_seed_values

    def test_get(self) -> None:
        # Check the DEFAULT section
        # N.B.: All values read from config files are read as str and only later converted by the
        # options parser to the expected destination type; so we ensure we're comparing strings
        # here.
        for option, value in self.default_seed_values.items():
            # Both config files have the seed values.
            assert self.config.get(section="DEFAULT", option=option) == [str(value), str(value)]
        for option, value in FILE_1.default_values.items():
            # Only FILE_1 has explicit DEFAULT values.
            assert self.config.get(section="DEFAULT", option=option) == [str(value)]

        # Check the combined values.
        for section, section_values in self.expected_combined_values.items():
            for option, value_list in section_values.items():
                assert self.config.get(section=section, option=option) == value_list

    def test_empty(self) -> None:
        config = Config.load([])
        assert config.sources() == []


def test_toml_serializer() -> None:
    original_values: Dict = {
        "GLOBAL": {
            "truthy": True,
            "falsy": False,
            "int": 0,
            "float": 0.0,
            "word": "hello there",
            "listy": ["a", "b", "c"],
            "map": {"a": 0, "b": 1},
        },
        "some-subsystem": {"o": ""},
    }
    assert TomlSerializer(original_values).normalize() == {
        "GLOBAL": {**original_values["GLOBAL"], "map": "{'a': 0, 'b': 1}"},
        "some-subsystem": {"o": ""},
    }


def test_toml_serializer_list_add_remove() -> None:
    original_values = {"GLOBAL": {"backend_packages.add": ["added"]}}
    assert TomlSerializer(original_values).normalize() == {  # type: ignore[arg-type]
        "GLOBAL": {"backend_packages": "+['added']"}
    }
