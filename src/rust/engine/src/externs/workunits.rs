// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PySequence};
use workunit_store::Metric;

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(all_counter_names, m)?)?;
    m.add_function(wrap_pyfunction!(decode_observation_histogram, m)?)?;
    Ok(())
}

#[pyfunction]
fn all_counter_names() -> Vec<String> {
    Metric::all_metrics()
}

#[pyfunction]
fn decode_observation_histogram<'py>(
    py: Python<'py>,
    encoded: &Bound<'py, PyBytes>,
    percentiles: &Bound<'py, PySequence>,
) -> PyResult<Bound<'py, PyDict>> {
    let encoded = encoded.as_bytes().to_vec();
    let histogram = py.detach(move || {
        let mut reader = encoded.as_slice();
        hdrhistogram::serialization::Deserializer::new()
            .deserialize::<u64, _>(&mut reader)
            .map_err(|err| PyErr::new::<pyo3::exceptions::PyValueError, _>(err.to_string()))
    })?;

    let result = PyDict::new(py);
    let mean = histogram.mean();
    let total_observations = histogram.len();
    result.set_item("min", histogram.min())?;
    result.set_item("max", histogram.max())?;
    result.set_item("mean", mean)?;
    result.set_item("std_dev", histogram.stdev())?;
    result.set_item("total_observations", total_observations)?;
    result.set_item("sum", (mean * total_observations as f64) as u64)?;

    for percentile in percentiles.try_iter()? {
        let percentile: f64 = percentile?.extract()?;
        result.set_item(
            format!("p{}", percentile),
            histogram.value_at_percentile(percentile),
        )?;
    }

    Ok(result)
}
