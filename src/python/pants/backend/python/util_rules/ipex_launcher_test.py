# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.util_rules.ipex_launcher import _requirements_from_pex_info


def test_requirements_from_pex_info_distributions() -> None:
    assert _requirements_from_pex_info(
        {
            "distributions": {
                "requests-2.32.5-py3-none-any.whl": "",
                "typing_extensions-4.15.0-py3-none-any.whl": "",
            },
            "requirements": ["requests"],
        }
    ) == ("requests==2.32.5", "typing-extensions==4.15.0")


def test_requirements_from_pex_info_falls_back_to_requirements() -> None:
    assert _requirements_from_pex_info({"requirements": ["requests>=2"]}) == ("requests>=2",)
