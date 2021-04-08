# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from __future__ import annotations

from typing import Any

# from pants.util.ordered_set import FrozenOrderedSet
import toml
from pkg_resources import Requirement

toml2_str_ex = """[tool.poetry]
name = "poetry_tinker"
version = "0.1.0"
description = ""
authors = ["Liam Wilson <lswilson0709@gmail.com>"]

[tool.poetry.dependencies]
python = "^3.8"
poetry = {git = "https://github.com/python-poetry/poetry.git"}
requests = {extras = ["security"], version = "^2.25.1"}

[tool.poetry.dev-dependencies]
isort = ">=5.5.1,<5.6"

[build-system]
requires = ["poetry-core>=1.0.0"]
build-backend = "poetry.core.masonry.api"
"""

toml_str_ex = """[tool.poetry]
name = "poetry-demo"
version = "0.1.0"
description = ""
authors = ["Eric Arellano <ericarellano@me.com>"]
[tool.poetry.dependencies]
# python = "==3.8"
"pantsbuild.pants" = ">=2.2.0"
[tool.poetry.dev-dependencies]
"foo" = ">1.0.0"
[build-system]
requires = ["poetry-core>=1.0.0"]
build-backend = "poetry.core.masonry.api"
"""


def parse_pyproject_toml(toml_contents: str) -> set[Requirement]:
    parsed = toml.loads(toml_contents)

    def parse_single_dependency(proj_name: str, attributes: str | dict[str, Any]) -> Requirement:
        if isinstance(attributes, str):
            return Requirement.parse(f"{proj_name}{attributes}")

    poetry_vals = parsed["tool"]["poetry"]
    all_req_raw = {**poetry_vals["dependencies"], **poetry_vals["dev-dependencies"]}

    return {parse_single_dependency(proj, attr) for proj, attr in all_req_raw.items()}


def parse_poetry_lock(lock_contents: str) -> set[Requirement]:
    pass


print(parse_pyproject_toml(toml_str_ex))
