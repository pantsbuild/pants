// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use pyo3::prelude::{PyModule, PyResult, Python};

// Sub-modules with intrinsic implementations.
mod dep_inference;
mod digests;
mod docker;
mod interactive_process;
mod process;
mod values;

pub use interactive_process::interactive_process_inner;

pub fn register(py: Python, m: &PyModule) -> PyResult<()> {
    dep_inference::register(py, m)?;
    digests::register(py, m)?;
    docker::register(py, m)?;
    interactive_process::register(py, m)?;
    process::register(py, m)?;
    values::register(py, m)?;

    Ok(())
}
