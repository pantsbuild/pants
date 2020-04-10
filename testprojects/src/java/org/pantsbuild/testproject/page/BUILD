# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

page(name="readme",
     sources=["README.md"],
     links=[
       'examples/src/java/org/pantsbuild/example/hello/main:readme',
       ':circular',
     ]
)

page(name="circular",
     sources=["circular.md"],
     links=[
       ':readme',
     ]
)

page(
  name="senserst",
  sources=["sense.rst"],
)
