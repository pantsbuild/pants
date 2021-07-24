// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::path::PathBuf;

use pyo3::prelude::*;

use log::Log;
use logging::logger::PANTS_LOGGER;
use logging::Logger;

pub(crate) fn register(m: &PyModule) -> PyResult<()> {
  m.add_function(wrap_pyfunction!(flush_log, m)?)?;
  m.add_function(wrap_pyfunction!(write_log, m)?)?;
  m.add_function(wrap_pyfunction!(set_per_run_log_path, m)?)?;
  Ok(())
}

#[pyfunction]
fn flush_log() {
  PANTS_LOGGER.flush()
}

#[pyfunction]
fn write_log(msg: &str, level: u64, target: &str, py: Python) {
  py.allow_threads(|| Logger::log_from_python(msg, level, target).expect("Error logging message"))
}

// TODO: Needs to be thread-local / associated with the Console.
#[pyfunction]
fn set_per_run_log_path(log_path: Option<String>, py: Python) {
  py.allow_threads(|| PANTS_LOGGER.set_per_run_logs(log_path.map(PathBuf::from)))
}
