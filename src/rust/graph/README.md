To build for development, run:

    rustc --crate-type=dylib graph.rs

To build for deployment, enable optimization:

    rustc -O --crate-type=dylib graph.rs
