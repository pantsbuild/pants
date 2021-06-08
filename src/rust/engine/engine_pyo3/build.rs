// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

fn main() {
  // NB: The native extension only works with the Python interpreter version it was built with
  // (e.g. Python 3.7 vs 3.8).
  println!("cargo:rerun-if-env-changed=PY");

  if cfg!(target_os = "macos") {
    // N.B. On OSX, we force weak linking by passing the param `-undefined dynamic_lookup` to
    // the underlying linker. This avoids "missing symbol" errors for Python symbols
    // (e.g. `_PyImport_ImportModule`) at build time when bundling the PyO3 sources.
    // The missing symbols will instead by dynamically resolved in the address space of the parent
    // binary (e.g. `python`) at runtime. We do this to avoid needing to link to libpython
    // (which would constrain us to specific versions of Python).
    println!("cargo:rustc-cdylib-link-arg=-undefined");
    println!("cargo:rustc-cdylib-link-arg=dynamic_lookup");
  }
}
