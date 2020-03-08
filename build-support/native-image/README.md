native-image `META-INF/`
===========================

**NOTE: currently, these instructions will only work when used from the script in this repo [^1]! Image building in general is currently blocked on https://github.com/oracle/graal/issues/1448.*

*This directory contains special configuration files recognized by the `native-image` tool when embedded in a jar. This embedded configuration allows any user with some version of the Graal VM to fetch the `org.pantsbuild:zinc-compiler` jar and run `native-image -jar` to produce a native executable of the pants zinc wrapper without any additional arguments.*

The Graal VM's `native-image` tool[^2] converts JVM bytecode to a native compiled executable[^3] executing via the Substrate VM. The `native-image` tool is not yet immediately compatible with all JVM code[^4], but the tool is stable and featureful enough to successfully build many codebases with a mixture of (mostly) automated and (some) manual configuration.

The `native-image` tool accepts JSON configuration files which overcome some of the current limitations[^4]:
1. `reflect-config.json`: The largest file, this would typically be generated automatically[^6].
  - Some manual edits may be necessary[^7].
2. `resource-config.json`: Should also be generated automatically[^6].
  - Some manual edits may be necessary[^8].
3. `substitutions.json`: Always manually generated, mocks out code that otherwise won't compile or run via `native-image`[^9].
4. `native-image.properties`: Read by the `native-image` tool to get command-line arguments to use when executing on the jar, and accepts a `${.}` template syntax[^5].
  - `native-image --help` describes many high-level command-line options which are converted to longer-form options when `native-image` is executing. `native-image --expert-options-all` describes all options.
  - The arguments `--enable-all-security-services`, `--allow-incomplete-classpath`, and `--report-unsupported-elements-at-runtime` are going to be desired for almost all builds.
  - The argument `--delay-class-initialization-to-runtime` delays initialization of classes until runtime (the `native-image` tool otherwise executes all static initializers at build time). Determining the appropriate classes to mark in this way can sometimes be a manual process[^10].

Note that all json resource files can be inspected and transformed with the `jq` command-line tool [^11]. This is what is done in the script in [^1].

# Automatically generating a zinc native-image for your repo

**NOTE:** This will allow creating a zinc native-image of code containing macros, but the image currently has to be manually regenerated whenever adding or modifying macros!

The script in [^1] will run on OSX or Linux (the `ubuntu:latest` container on docker hub is known to work). The script can be run to test out native-image zinc compiles as follows:

``` bash
$ cd /your/pants/codebase
$ /path/to/your/pants/checkout/build-support/native-image/generate-native-image-for-pants-targets.bash ::
```

After a long bootstrap process, the arguments are forwarded to a pants invocation which runs with reflection tracing. The `NATIVE_IMAGE_EXTRA_ARGS` environment variable can be used to add any necessary arguments to the `native-image` invocation (the scalactic resource bundle is necessary for any repo using scalatest). The above will build an image suitable for all targets in the repo (`::`) for the current platform. The script will generate a different output file `zinc-pants-native-{Darwin,Linux}` depending upon whether it is run on OSX or Linux.

*Note:* if the native-image build fails, and you see the following in the output:
``` bash
Caused by: java.lang.VerifyError: class scala.tools.nsc.Global overrides final method isDeveloper.()Z
```

Please re-run the script at most two more times. This can occur nondeterministically for some reason right now. https://github.com/pantsbuild/pants/issues/7955 is intended to cover solving this issue, along with others.


## Updating the zinc native-image

This is a developing story. Currently, the script will idempotently create or update a directory in the pwd named `generated-reflect-config/` with the results of the reflection tracing. This directory will contain 5 files -- 4 json config files, and one `BUILD` file. This directory can be checked in and updated over time -- subsequent runs of the script will never remove information from previous runs.

*Note:* the script does *not* need to be run over the whole repo (`::`) at once! Since the compile run with reflection tracing has parallelism set to 1, this initial run can take a long time. Initially, it's possible to run the script over batched sections of your repo (e.g. using `./pants list` and `--spec-file`), until all targets are covered.

The image may begin failing to build -- this can happen e.g. if you used to use a macro in your repo, but no longer do, the build will fail when scanning reflect config entries. If this happens, you can always `rm -rfv generated-reflect-config/` and run the script again (although you will have to rebuild it for your whole repo again in this case).

[^1]: ./generate-native-image-for-pants-targets.bash

[^2]: https://github.com/oracle/graal/tree/master/substratevm

[^3]: https://www.graalvm.org/docs/reference-manual/aot-compilation/

[^4]: https://github.com/oracle/graal/blob/master/substratevm/LIMITATIONS.md

[^5]: https://medium.com/graalvm/simplifying-native-image-generation-with-maven-plugin-and-embeddable-configuration-d5b283b92f57

[^6]: https://github.com/oracle/graal/blob/master/substratevm/CONFIGURE.md

[^7]: https://github.com/oracle/graal/blob/master/substratevm/REFLECTION.md

[^8]: https://github.com/oracle/graal/blob/master/substratevm/RESOURCES.md

[^9]: https://github.com/pantsbuild/pants/tree/master/src/scala/org/pantsbuild/zinc/compiler/native-image-substitutions

[^10]: https://medium.com/graalvm/understanding-class-initialization-in-graalvm-native-image-generation-d765b7e4d6ed

[^11]: https://stedolan.github.io/jq/
