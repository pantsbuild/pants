# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Shows java working with jaxb generations.

junit_tests(name='usejaxb',
  sources=['UseJaxbTest.java',],
  dependencies=[
    pants('3rdparty:junit'),
    pants('src/java/com/pants/examples/jaxb/reader'),
    pants('src/resources/com/pants/example/names'),
  ],
)