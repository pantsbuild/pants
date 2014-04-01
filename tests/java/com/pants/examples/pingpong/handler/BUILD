# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_tests(name='handler',
  dependencies=[
    pants('3rdparty:easymock'),
    pants('3rdparty:guava'),
    pants('3rdparty:junit'),
    pants('3rdparty/jvm/com/twitter/common:base'),
    pants('3rdparty/jvm/com/twitter/common:testing-easymock'),
    pants('src/java/com/twitter/common/examples/pingpong/handler'),
  ],
  sources=globs('*.java'),
)
