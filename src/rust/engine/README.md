A native-code implementation of the pants v2 engine. See:

    https://docs.google.com/document/d/1C64MreDeVoZAl3HrqtWUVE-qnj3MyWW0NQ52xeWw/edit

To build for development, run:

    cargo build

To run tests for any particular crate, cd into it and run:

    cargo test

Or to run tests for all crates, run:

    ./run-all-tests.sh

To build for release, and enable optimization:

    cargo build --release

For development purposes, it's usually fastest to then place the resulting shared library directly
where `binary_utils` would fetch them to (TODO: expand before commit):

    cp target/release/libengine.dylib ~/.cache/pants/dylib/native-engine/mac/10.11/0.0.1/native-engine
