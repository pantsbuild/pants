import itertools
from dataclasses import dataclass
from typing import List

from . import lib, v2
from .lib import ByoLinter
from ..python.target_types import ConsoleScript

confs = [
    ByoLinter(
        options_scope='byo_shellcheck',
        name="Shellcheck",
        help="A shell linter based on your installed shellcheck",
        command="shellcheck",
        file_extensions=[".sh"],
    ),
    ByoLinter(
        options_scope='byo_markdownlint',
        name="MarkdownLint",
        help="A markdown linter based on your installed markdown lint.",
        command="markdownlint",
        tools=["node"],
        file_extensions=[".md"],
    )
]



def target_types():
    return []


def rules():
    # return lib.shellcheck_rules()
    # return lib.markdownlint_rules()
    # return v2.rules()
    return list(itertools.chain.from_iterable(conf.rules() for conf in confs))