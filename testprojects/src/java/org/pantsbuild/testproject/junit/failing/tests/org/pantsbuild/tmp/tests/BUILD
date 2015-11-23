target(name='tests',
  dependencies=[
    ':one',
    ':two',
    ':three',
  ],
)

java_library(name='base',
  dependencies=['3rdparty:junit'],
)

java_tests(name='one',
  sources=['OneTest.java'],
  dependencies=[':base'],
  strict_deps=False,
)

java_tests(name='two',
  sources=['TwoTest.java'],
  dependencies=[':base'],
  strict_deps=False,
)

java_tests(name='three',
  sources=['subtest/ThreeTest.java'],
  dependencies=[':base'],
  strict_deps=False,
)
