# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path
from types import ModuleType
from typing import Any, Union, cast

from pkg_resources import DefaultProvider, ZipProvider, get_provider

from pants.util.memo import memoized


@memoized
def get_resource_string(module: ModuleType, rel_path: Path) -> str:
  # This technique was taken from pex/pex_builder.py in the pex repo.
  provider: Any = get_provider(module.__name__)
  if not isinstance(provider, DefaultProvider):
    mod = __import__(module.__name__, fromlist=['ignore'])
    provider = ZipProvider(mod)                            # type: ignore[call-arg]
  provider: Union[DefaultProvider, ZipProvider] = provider # type: ignore[no-redef]
  resource_string = provider.get_resource_string(module.__name__, str(rel_path))
  return cast(str, resource_string)
