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
  clippy::used_underscore_binding
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
  // NB: The native extension only works with the Python interpreter version it was built with
  // (e.g. Python 3.7 vs 3.8).
  println!("cargo:rerun-if-env-changed=PY");

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
