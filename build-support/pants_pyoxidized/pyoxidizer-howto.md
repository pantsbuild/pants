NOTES:


Run `./pants` with interpreter constraints that match the PyOxidizer interpreter constraints. `native_engine.so` and the Pants `.whl` file _MUST_ be built with constraints that match the version of Python that PyOxidizer wants to use.

Run `./pants package --pyoxidizer-interpreter-constraints="['CPython==3.9.*']" build-support/pants_pyoxidized:pants_pyoxidized_experimental`

The binary will be `dist/pants/aarch64-apple-darwin/debug/install/pants` -- this will not work on the pants repo itself (yet?)


# Code signing errors?


Obtain a self-signed certificate using info at at https://developer.apple.com/library/archive/documentation/Security/Conceptual/CodeSigningGuide/Procedures/Procedures.html

I've called mine "pyox-test".

Get native engine to build first (i.e. run `./pants` and wait for rust to finish doing its thing).

Run `codesign -s pyox-test dist/pants/aarch64-apple-darwin/debug/install/lib/pants/engine/internals/native_engine.so`
