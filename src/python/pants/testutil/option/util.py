# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Dict, Iterable, Optional

from pants.option.options_bootstrapper import OptionsBootstrapper


def create_options_bootstrapper(
    *, args: Optional[Iterable[str]] = None, env: Optional[Dict[str, str]] = None,
) -> OptionsBootstrapper:
    return OptionsBootstrapper.create(
        args=("--pants-config-files=[]", *(args or [])), env=env or {},
    )
