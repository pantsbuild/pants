# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_library(name='dependency',
             sources=['Dependency.java'],
             )

java_library(name='hello',
             sources=['Hello.java'],
             )

java_library(name='main',
             sources=['ExampleMain.java'],
             dependencies=[
               ':hello',
               ':dependency'
             ]
             )
