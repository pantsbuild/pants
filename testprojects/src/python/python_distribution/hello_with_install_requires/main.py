# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pycountry
from hello_package import hello

if __name__ == "__main__":
    hello.hello()
    print(pycountry.countries.get(alpha_2="US").name)
