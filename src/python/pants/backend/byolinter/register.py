import itertools

from . import lib
from .lib import ByoLinter

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
    return list(itertools.chain.from_iterable(conf.rules() for conf in confs))