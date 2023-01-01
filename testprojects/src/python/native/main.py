# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from native import name

if __name__ == "__main__":
    print(f"Hello {name.get_name()}")
