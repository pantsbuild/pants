java_tests(name='customrunner',
  sources=['TestsWithThrowingRunner.java'],
  dependencies=[
    '3rdparty:junit',
    ':throwing_runner',
    ],
)

java_library(name='throwing_runner',
  sources=['ThrowingRunner.java'],
  dependencies=[
    '3rdparty:junit',
  ]
)