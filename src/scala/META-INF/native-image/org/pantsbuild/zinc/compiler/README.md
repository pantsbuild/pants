native-image `META-INF/`
===========================

*This directory contains special configuration files recognized by the `native-image` tool when embedded in a jar. This embedded configuration allows any user with some version of the Graal VM to fetch the `org.pantsbuild:zinc-compiler` jar and run `native-image -jar` to produce a native executable of the pants zinc wrapper without any additional arguments.*

The Graal VM's `native-image` tool[^1] converts JVM bytecode to a native compiled executable[^2] executing via the Substrate VM. The `native-image` tool is not yet immediately compatible with all JVM code[^3], but the tool is stable and featureful enough to successfully build many codebases with a mixture of (mostly) automated and (some) manual configuration.

The `native-image` tool accepts JSON configuration files which overcome some of the current limitations[^3]:
1. `reflect-config.json`: The largest file, this would typically be generated automatically[^5].
  - Some manual edits may be necessary[^6].
2. `resource-config.json`: Should also be generated automatically[^5].
  - Some manual edits may be necessary[^7].
3. `substitutions.json`: Always manually generated, mocks out code that otherwise won't compile or run via `native-image`[^8].
4. `native-image.properties`: Read by the `native-image` tool to get command-line arguments to use when executing on the jar, and accepts a `${.}` template syntax[^4].
  - `native-image --help` describes many high-level command-line options which are converted to longer-form options when `native-image` is executing. `native-image --expert-options-all` describes all options.
  - The arguments `--enable-all-security-services`, `--allow-incomplete-classpath`, and `--report-unsupported-elements-at-runtime` are going to be desired for almost all builds.
  - The argument `--delay-class-initialization-to-runtime` delays initialization of classes until runtime (the `native-image` tool otherwise executes all static initializers at build time). Determining the appropriate classes to mark in this way can sometimes be a manual process[^9].


Note that all json resource files should be formatted by piping them into `jq --sort-keys .`[^10]. This makes diffs easier to see by consistently formatting the output and deterministically sorting string object keys.


[^1]: https://github.com/oracle/graal/tree/master/substratevm

[^2]: https://www.graalvm.org/docs/reference-manual/aot-compilation/

[^3]: https://github.com/oracle/graal/blob/master/substratevm/LIMITATIONS.md

[^4]: https://medium.com/graalvm/simplifying-native-image-generation-with-maven-plugin-and-embeddable-configuration-d5b283b92f57

[^5]: https://github.com/oracle/graal/blob/master/substratevm/CONFIGURE.md

[^6]: https://github.com/oracle/graal/blob/master/substratevm/REFLECTION.md

[^7]: https://github.com/oracle/graal/blob/master/substratevm/RESOURCES.md

[^8]: https://github.com/pantsbuild/pants/tree/master/src/scala/org/pantsbuild/zinc/compiler/native-image-substitutions

[^9]: https://medium.com/graalvm/understanding-class-initialization-in-graalvm-native-image-generation-d765b7e4d6ed

[^10]: https://stedolan.github.io/jq/
