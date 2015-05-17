# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_library(name='greet',
  dependencies=[],
  sources=globs('*.java'),
  provides=artifact(
    org='org.pantsbuild.testproject.publish',
    name='hello-greet',
    repo=testing,
    publication_metadata=ossrh(
      description='A simple greeter.',
      url='https://github.com/pantsbuild/pants/tree/master/'
          'testprojects/src/java/org/pantsbuild/testproject/publish/hello/greet',
      licenses=[
        license(
          name='MIT License',
          url='http://www.opensource.org/licenses/mit-license.php'
        ),
        license(
          name='To Ill',
          url='http://brassmonkey.example.org/',
          comments='Covers legacy releases.'
        )
      ],
      developers=[
        developer(
          user_id='jane'
        ),
        developer(
          name='George Jones'
        ),
        developer(
          email='charlie@example.com',
          roles=[
            'greenman',
            'wildcard'
          ]
        ),
        developer(
          name='Jack Spratt',
          email='jack.spratt@example.com'
        )
      ],
      scm=github(
        user='pantsbuild',
        repo='pants'
      )
    )
 ),
)
