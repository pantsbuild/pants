junit_tests(name='cucumber',
  sources=globs('*.java'),
  dependencies=[
    pants('3rdparty:junit'),
    pants('src/java/com/pants/examples/unicode/cucumber'),
  ],
)

jar_library(name='info.cukes.cucumber-core',
    jars=[
      jar(org='info.cukes',
          name='cucumber-core',
          rev='1.1.7'),
    ],
)
