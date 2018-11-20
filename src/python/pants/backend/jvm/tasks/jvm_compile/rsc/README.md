Rsc Compile
===========

Rsc is a new scala compiler that produces outlines instead of bytecode (https://github.com/twitter/rsc). This task uses that compiler and its toolchain to produce jars that scalac via zinc can compile against to produce bytecode containing jars.

In order to invoke `rsc`, you can invoke on a jvm target like:

    $ ./pants -ldebug \
              --resolve-{coursier,ivy}-capture-snapshots \
              --no-compile-{rsc,zinc}-incremental \
              --compile-{rsc,zinc}-execution-strategy=hermetic \
              --jvm-platform-compiler=rsc \
              clean-all compile testprojects/src/scala/org/pantsbuild/testproject/mutual:bin
