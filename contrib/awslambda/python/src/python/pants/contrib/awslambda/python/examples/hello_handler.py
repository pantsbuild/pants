# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pycountry

from pants.contrib.awslambda.python.examples.hello_lib import say_hello


def handler(event, context):
    usa = pycountry.countries.get(alpha_2="US").name
    say_hello("from the {}".format(usa))
