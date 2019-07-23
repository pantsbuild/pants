zinc native-image substitutions
===============================

*This directory contains source files mocking out any methods that for whatever reason won't compile or run correctly with `native-image`.*

The Graal VM's `native-image` tool[^1] converts JVM bytecode to a native compiled executable[^2] executing via the Substrate VM. The tool is not yet immediately compatible with all JVM code[^3], so SubstrateVM's *substitutions* facility allows mocking out code that doesn't compile or run correctly[^4].

In ScalaDays 2018, a demo was presented of executing Scalac with the `native-image` tool[^5]. This directory contains the substitutions directly from that demo's repository, along with a small additional substitution which was necessary for extending that work to cover the zinc incremental compiler[^6].

As described in [^4] and demonstrated in [^5], substitutions also require a JSON configuration file to have `native-image` recognize them. That configuration is stored in `META-INF/`, see [^7].

[^1]: https://github.com/oracle/graal/tree/master/substratevm

[^2]: https://www.graalvm.org/docs/reference-manual/aot-compilation/

[^3]: https://github.com/oracle/graal/blob/master/substratevm/LIMITATIONS.md

[^4]: https://medium.com/graalvm/instant-netty-startup-using-graalvm-native-image-generation-ed6f14ff7692

[^5]: https://github.com/graalvm/graalvm-demos/tree/master/scala-days-2018/scalac-native

[^6]: https://github.com/sbt/zinc

[^7]: https://github.com/pantsbuild/pants/tree/master/src/scala/META-INF/native-image/org/pantsbuild/zinc/compiler
