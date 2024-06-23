// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

fn main() {
    pyo3_build_config::add_extension_module_link_args();

    // NB: The native extension only works with the Python interpreter version it was built with
    // (e.g. Python 3.7 vs 3.8).
    println!("cargo:rerun-if-env-changed=PY");
    if let Ok(py_var) = std::env::var("PY") {
        println!("cargo:rerun-if-changed={py_var}");
    }
}
