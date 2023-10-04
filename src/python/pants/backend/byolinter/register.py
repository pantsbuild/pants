import itertools
from dataclasses import dataclass
from typing import List

from . import lib, v2
from .lib import ByoLinter, SystemBinaryExecutable
from ..python.target_types import ConsoleScript



flake8_executor = dict(
    main=ConsoleScript("flake8"),
    requirements=["flake8>=5.0.4,<7"],
    resolve="byo_flake8",
)


confs = [
    ByoLinter(
        options_scope='byo_shellcheck',
        name="Shellcheck",
        help="A shell linter based on your installed shellcheck",
        executable=SystemBinaryExecutable("shellcheck"),
        file_extensions=[".sh"],
        file_glob_include=["**/*.sh"],
        file_glob_exclude=[],
    ),
    ByoLinter(
        options_scope='byo_markdownlint',
        name="MarkdownLint",
        help="A markdown linter based on your installed markdown lint.",
        executable=SystemBinaryExecutable("markdownlint", tools=["node"]),
        file_extensions=[".md"],
        file_glob_include=["**/*.md"],
        file_glob_exclude=["README.md"],
    )
]



def target_types():
    return []


def rules():
    # return lib.shellcheck_rules()
    # return lib.markdownlint_rules()
    # return v2.rules()
    return list(itertools.chain.from_iterable(conf.rules() for conf in confs))