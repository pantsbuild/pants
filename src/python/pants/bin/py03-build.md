NOTES:

Obtain a self-signed certificate using info at at https://developer.apple.com/library/archive/documentation/Security/Conceptual/CodeSigningGuide/Procedures/Procedures.html

I've called mine "py03-test"

Get native engine to build first.

Run `codesign -s py03-test /Users/chrisjrn/src/pants/dist/src.python.pants.bin/pants_oxidized_experimental/aarch64-apple-darwin/debug/install/lib/pants/engine/internals/native_engine.so`

Run `./pants --no-pantsd --no-remote-cache-write package --pyoxidizer-args="--system-rust --target-triple=aarch64-apple-darwin" src/python/pants/bin:pants_oxidized_experimental`

Run `_PANTS_VERSION_OVERRIDE="2.14.0.dev" dist/src.python.pants.bin/pants_oxidized_experimental/aarch64-apple-darwin/debug/install/pants_oxidized_experimental --no-pantsd`