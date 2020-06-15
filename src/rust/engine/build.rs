// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#![deny(warnings)]
// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![deny(
  clippy::all,
  clippy::default_trait_access,
  clippy::expl_impl_clone_on_copy,
  clippy::if_not_else,
  clippy::needless_continue,
  clippy::unseparated_literal_suffix,
  // TODO: Falsely triggers for async/await:
  //   see https://github.com/rust-lang/rust-clippy/issues/5360
  // clippy::used_underscore_binding
)]
// It is often more clear to show that nothing is being moved.
#![allow(clippy::match_ref_pats)]
// Subjective style.
#![allow(
  clippy::len_without_is_empty,
  clippy::redundant_field_names,
  clippy::too_many_arguments
)]
// Default isn't as big a deal as people seem to think it is.
#![allow(clippy::new_without_default, clippy::new_ret_no_self)]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![allow(clippy::mutex_atomic)]

fn main() {
  // NB: When built with Python 3, `native_engine.so` only works with a Python 3 interpreter.
  // When built with Python 2, it works with both Python 2 and Python 3.
  // So, we check to see if the under-the-hood interpreter has changed and rebuild the native engine
  // when needed.
  println!("cargo:rerun-if-env-changed=PY");

  if cfg!(target_os = "linux") {
    // We depend on grpcio, which uses C++.
    // On Linux, with g++, some part of that compilation depends on
    // __gxx_personality_v0 which is present in the C++ standard library.
    // I don't know why. It shouldn't, and before grpcio 0.2.0, it didn't.
    println!("cargo:rustc-cdylib-link-arg=-lstdc++");
  }

  if cfg!(target_os = "macos") {
    // N.B. On OSX, we force weak linking by passing the param `-undefined dynamic_lookup` to
    // the underlying linker. This avoids "missing symbol" errors for Python symbols
    // (e.g. `_PyImport_ImportModule`) at build time when bundling the cpython sources.
    // The missing symbols will instead by dynamically resolved in the address space of the parent
    // binary (e.g. `python`) at runtime. We do this to avoid needing to link to libpython
    // (which would constrain us to specific versions of Python).
    println!("cargo:rustc-cdylib-link-arg=-undefined");
    println!("cargo:rustc-cdylib-link-arg=dynamic_lookup");
  }
}
