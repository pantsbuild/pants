import itertools
from dataclasses import dataclass
from typing import List

from . import lib, v2
from .lib import ByoTool, SystemBinaryExecutable, PythonToolExecutable
from ..python.target_types import ConsoleScript






confs = [
    ByoTool(
        options_scope='byo_markdownlint',
        name="MarkdownLint",
        help="A markdown linter based on your installed markdown lint.",
        executable=SystemBinaryExecutable("markdownlint", tools=["node"]),
        file_glob_include=["**/*.md"],
        file_glob_exclude=["README.md"],
        goal="lint",
    ),
    ByoTool(
        options_scope='byo_flake8',
        name="byo_Flake8",
        help="byo flake8",
        executable=PythonToolExecutable(
            main=ConsoleScript("flake8"),
            requirements=["flake8>=5.0.4,<7"],
            resolve="byo_flake8",
        ),
        file_glob_include=["**/*.py"],
        file_glob_exclude=[],
        goal="lint",
    ),
    # ByoTool(
    #     options_scope='byo_black',
    #     name="byo_Black",
    #     help="byo black",
    #     executable=PythonToolExecutable(
    #         main=ConsoleScript("black"),
    #         requirements=[
    #             "black>=22.6.0,<24",
    #             'typing-extensions>=3.10.0.0; python_version < "3.10"',
    #         ],
    #         resolve="byo_black",
    #     ),
    #     file_glob_include=["**/*.py"],
    #     file_glob_exclude=["pants-plugins/**"],
    #     goal="fmt",
    # )
]



def target_types():
    return []


def rules():
    # return lib.shellcheck_rules()
    # return lib.markdownlint_rules()
    # return v2.rules()
    return list(itertools.chain.from_iterable(conf.rules() for conf in confs))