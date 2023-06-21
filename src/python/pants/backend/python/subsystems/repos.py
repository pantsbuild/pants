# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import cast

from pants.base.deprecated import resolve_conflicting_options
from pants.option.option_types import StrListOption
from pants.option.subsystem import Subsystem
from pants.util.docutil import doc_url
from pants.util.strutil import help_text, softwrap


class PythonRepos(Subsystem):
    options_scope = "python-repos"
    help = help_text(
        """
        External Python code repositories, such as PyPI.

        These options may be used to point to custom package indexes when resolving requirements.
        """
    )

    pypi_index = "https://pypi.org/simple/"

    _find_links = StrListOption(
        help=softwrap(
            """
            URLs and/or file paths corresponding to pip's `--find-links` option.

            Per [pip's documentation](https://pip.pypa.io/en/stable/cli/pip_wheel/?highlight=find%20links#cmdoption-f),
            URLs should be to HTML files with links to `.whl` and/or
            sdist files. Local paths must be absolute, and can either be to an HTML file with
            links or to a directory with `.whl` and/or sdist files, e.g.
            `file:///Users/pantsbuild/prebuilt_wheels`.

            For local paths, you may want to use the option `[python-repos].path_mappings`.
            """
        )
    )
    _repos = StrListOption(
        help=softwrap(
            """
            URLs of code repositories to look for requirements. In Pip and Pex, this option
            corresponds to the `--find-links` option.
            """
        ),
        advanced=True,
        removal_version="3.0.0.dev0",
        removal_hint="A deprecated alias for `[python-repos].find_links`.",
    )
    indexes = StrListOption(
        default=[pypi_index],
        help=softwrap(
            """
            URLs of [PEP-503 compatible](https://peps.python.org/pep-0503/) code repository
            indexes to look for requirements.

            If set to an empty list, then Pex will use no indexes (meaning it will not use PyPI).
            """
        ),
        advanced=True,
    )

    path_mappings = StrListOption(
        help=softwrap(
            f"""
            Mappings to facilitate using local Python requirements when the absolute file paths
            are different on different users' machines. For example, the
            path `file:///Users/pantsbuild/prebuilt_wheels/django-3.1.1-py3-none-any.whl` could
            become `file://${{WHEELS_DIR}}/django-3.1.1-py3-none-any.whl`, where each user can
            configure what `WHEELS_DIR` points to on their machine.

            Expects values in the form `NAME|PATH`, e.g.
            `WHEELS_DIR|/Users/pantsbuild/prebuilt_wheels`. You can specify multiple
            entries in the list.

            This feature is intended to be used with `[python-repos].find_links`, rather than PEP
            440 direct reference requirements (see
            {doc_url("python-third-party-dependencies#local-requirements")}.
            `[python-repos].find_links` must be configured to a valid absolute path for the
            current machine.

            Tip: you can avoid each user needing to manually configure this option and
            `[python-repos].find_links` by using a common file location, along with Pants's
            interpolation support ({doc_url('options#config-file-interpolation')}. For example,
            in `pants.toml`, you could set both options to `%(buildroot)s/python_wheels`
            to point to the directory `python_wheels` in the root of
            your repository; or, use the path `%(env.HOME)s/pants_wheels` for the path
            `~/pants_wheels`. If you are not able to use a common path like this, then we
            recommend setting that each user set these options via a `.pants.rc` file
            ({doc_url('options#pantsrc-file')}.

            Note: Only takes effect if using Pex lockfiles, i.e. using the
            `generate-lockfiles` goal.
            """
        ),
        advanced=True,
    )

    @property
    def find_links(self) -> tuple[str, ...]:
        return cast(
            "tuple[str, ...]",
            resolve_conflicting_options(
                old_option="repos",
                new_option="find_links",
                old_scope=self.options_scope,
                new_scope=self.options_scope,
                old_container=self.options,
                new_container=self.options,
            ),
        )
