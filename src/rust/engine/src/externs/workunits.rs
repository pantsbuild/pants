// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use pyo3::prelude::*;
use workunit_store::Metric;

pub fn register(m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(all_counter_names, m)?)?;
    Ok(())
}

#[pyfunction]
fn all_counter_names() -> Vec<String> {
    Metric::all_metrics()
}
