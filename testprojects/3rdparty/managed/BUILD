# This file is used to integration test the managed_jar_libraries factory for managed dependencies
# and jar libraries.
# It also serves as a very simple example of how it might be used.

managed_jar_libraries(name='managed',
  artifacts=[
    jar('info.cukes', 'cucumber-core', '1.2.4'),
    jar('org.eclipse.jetty', 'jetty-jsp', '9.2.9.v20150224'),
    jar('jersey', 'jersey', '0.7-ea', classifier='sources'),
    ':args4j.args4j',
  ],
)

jar_library(name='args4j.args4j',
  jars=[
    jar('args4j', 'args4j', '2.32'),
  ],
  managed_dependencies=':managed', # This line is unnecessary if ':managed' is the default.
)

target(name='example-dependee',
  dependencies=[
    # Explicitly created:
    ':args4j.args4j',
    # Implicitly created:
    ':info.cukes.cucumber-core',
    ':jersey.jersey.sources',
    ':org.eclipse.jetty.jetty-jsp',
  ],
)
