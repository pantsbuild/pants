# Tests for dependency management integration.

managed_jar_dependencies(name='new-manager',
  artifacts=[
    jar('jersey', 'jersey', '0.7-ea'),
  ],
)

managed_jar_dependencies(name='old-manager',
  artifacts=[
    jar('jersey', 'jersey', '0.4-ea'),
  ],
)

jar_library(name='common-lib',
  jars=[
    jar('javax.annotation', 'jsr250-api', '1.0'),
    jar('javax.persistence', 'persistence-api', '1.0.2'),
    jar('javax.servlet', 'servlet-api', '2.5'),
    jar('com.sun.xml.txw2', 'txw2', '20110809'),
  ],
)

jar_library(name='old-jersey',
  jars=[
    jar('jersey', 'jersey'),
  ],
  managed_dependencies=':old-manager',
)

jar_library(name='new-jersey',
  jars=[
    jar('jersey', 'jersey'),
  ],
  managed_dependencies=':new-manager',
)

junit_tests(name='old-tests',
  sources=['OldTest.java'],
  dependencies=[
    '3rdparty:junit',
    ':common-lib',
    ':old-jersey',
  ],
)

junit_tests(name='new-tests',
  sources=['NewTest.java'],
  dependencies=[
    '3rdparty:junit',
    ':common-lib',
    ':new-jersey',
  ],
)
