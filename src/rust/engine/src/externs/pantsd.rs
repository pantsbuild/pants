// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashSet;

use pyo3::exceptions::PyException;
use pyo3::prelude::*;

use options::{Args, BuildRoot, Env, OptionParser};

pub fn register(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(pantsd_fingerprint_compute, m)?)?;
    Ok(())
}

/// Computes the current `pantsd` fingerprint.
///
/// Validates that the given expected pantsd fingerprint option names (all in the global scope)
/// match those registered in the native code (TODO: See `pantsd::fingerprinted_options` for more
/// information about this redundancy).
#[pyfunction]
fn pantsd_fingerprint_compute(expected_option_names: HashSet<String>) -> PyResult<String> {
    let build_root = BuildRoot::find().map_err(PyException::new_err)?;
    let options_parser =
        OptionParser::new(Env::capture_lossy().0, Args::argv()).map_err(PyException::new_err)?;

    let options = pantsd::fingerprinted_options(&build_root).map_err(PyException::new_err)?;
    let actual_option_names = options
        .into_iter()
        .map(|o| o.id.name_underscored())
        .collect::<HashSet<_>>();

    if expected_option_names != actual_option_names {
        return Err(PyException::new_err(format!(
            "The `daemon=True` options declared on the Python side did \
                not match the fingerprinted options from the Rust side: \
                {expected_option_names:?} vs {actual_option_names:?}"
        )));
    }

    pantsd::fingerprint_compute(&build_root, &options_parser).map_err(PyException::new_err)
}
