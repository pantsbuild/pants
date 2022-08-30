NOTES:


Run `./pants` with interpreter constraints that match the PyOxidizer interpreter constraints -- the initial `./pants` run will build `native_engine.so` and produce the pants wheel, which _MUST_ match the PyOxidizer interpreter version.

Run `./pants package --pyoxidizer-interpreter-constraints="['CPython==3.9.*']" src/python/pants/bin:pants_oxidized_experimental`

The binary will be `dist/src.python.pants.bin/pants_oxidized_experimental/aarch64-apple-darwin/debug/install/pants_oxidized_experimental` -- this will not work on the pants repo itself (yet?)


# Code signing errors?


Obtain a self-signed certificate using info at at https://developer.apple.com/library/archive/documentation/Security/Conceptual/CodeSigningGuide/Procedures/Procedures.html

I've called mine "pyox-test".

Get native engine to build first (i.e. run `./pants` and wait for rust to finish doing its thing).

Run `codesign -s pyox-test /Users/chrisjrn/src/pants/dist/src.python.pants.bin/pants_oxidized_experimental/aarch64-apple-darwin/debug/install/lib/pants/engine/internals/native_engine.so`
