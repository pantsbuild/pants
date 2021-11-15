// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

// File specific allowance, since the pyo3 macros produce underscore bindings.
#![allow(clippy::used_underscore_binding)]

use pyo3::prelude::*;

mod fs;
mod nailgun;
mod scheduler;
mod testutil;
mod workunits;

#[pymodule]
fn native_engine_pyo3(py: Python, m: &PyModule) -> PyResult<()> {
  self::fs::register(m)?;
  self::nailgun::register(py, m)?;
  self::scheduler::register(m)?;
  self::testutil::register(m)?;
  self::workunits::register(m)?;
  Ok(())
}
