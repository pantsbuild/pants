tensorflow_custom_op
====================

This directory implements the `ZeroOut` custom TensorFlow operator described in [Adding a New Op](https://www.tensorflow.org/guide/extend/op) in the TensorFlow docs. This can be built and tested with (see the [Pants Python README](https://www.pantsbuild.org/python_readme.html)):

``` bash
> ./pants test examples/tests/python/example_test/tensorflow_custom_op:: -- -vs
```

<!-- TODO(#6848): update this line when the limitation is removed! -->
Note that due to a current limitation (see [#6848](https://github.com/pantsbuild/pants/issues/6848)), this can only be run with the LLVM toolchain on OSX, which can be done with:

``` bash
./pants --native-build-step-toolchain-variant=llvm test examples/tests/python/example_test/tensorflow_custom_op:: -- -vs
```

or by setting the toolchain variant [option in `pants.toml`](https://www.pantsbuild.org/options.html).
