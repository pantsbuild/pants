target(name='only-15-directly',
       dependencies=[':jarversionincompatibility'])

target(name='alongside-16',
       dependencies=[':jarversionincompatibility',
                     ':guava-16',
                    ])


java_library(name='jarversionincompatibility',
             sources=['DependsOnRateLimiter.java'],
             dependencies=[':guava-15'])


jar_library(name='guava-15',
            jars=[jar('com.google.guava', 'guava', '15.0')])

jar_library(name='guava-16',
            jars=[jar('com.google.guava', 'guava', '16.0')])