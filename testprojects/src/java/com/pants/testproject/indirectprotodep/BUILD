# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jvm_binary(name='indirectprotodep',
           basename='indirectprotodep-example',
           dependencies=[
             'testprojects/src/protobuf/com/pants/testproject/indirectprotodep',
             '3rdparty:protobuf-java',
             ],
           source='ExampleMain.java',
           main='com.pants.testproject.indirectprotodep.ExampleMain',
           )
