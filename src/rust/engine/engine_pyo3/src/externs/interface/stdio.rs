// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::hash_map::HashMap;
use std::path::PathBuf;
use std::sync::Arc;

use log::Log;
use logging::logger::PANTS_LOGGER;
use logging::Logger;
use pyo3::buffer::PyBuffer;
use pyo3::exceptions::{PyException, PyIOError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyTuple;
use pyo3::types::PyType;
use pyo3::wrap_pyfunction;
use regex::Regex;

pub(crate) fn register(m: &PyModule) -> PyResult<()> {
  m.add_function(wrap_pyfunction!(flush_log, m)?)?;
  m.add_function(wrap_pyfunction!(write_log, m)?)?;
  m.add_function(wrap_pyfunction!(set_per_run_log_path, m)?)?;
  m.add_function(wrap_pyfunction!(stdio_initialize, m)?)?;
  m.add_function(wrap_pyfunction!(stdio_thread_console_set, m)?)?;
  m.add_function(wrap_pyfunction!(stdio_thread_console_clear, m)?)?;
  m.add_class::<PyStdioDestination>()?;
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

#[pyfunction]
fn stdio_initialize(
  level: u64,
  show_rust_3rdparty_logs: bool,
  use_color: bool,
  show_target: bool,
  log_levels_by_target: HashMap<String, u64>,
  literal_filters: Vec<String>,
  regex_filters: Vec<String>,
  log_file: String,
  py: Python,
) -> PyResult<&PyTuple> {
  py.allow_threads(|| {
    let regex_filters = regex_filters
      .iter()
      .map(|re|
        Regex::new(re).map_err(|e|
          PyValueError::new_err(
            format!(
              "Failed to parse warning filter. Please check the global option `--ignore-warnings`.\n\n{}",
              e,
            )
          )
        )
      )
      .collect::<Result<Vec<_>, _>>()?;

    Logger::init(
      level,
      show_rust_3rdparty_logs,
      use_color,
      show_target,
      log_levels_by_target,
      literal_filters,
      regex_filters,
      PathBuf::from(log_file),
    )
    .map_err(|s| PyIOError::new_err(format!("Could not initialize logging: {}", s)))
  })?;

  Ok(PyTuple::new(
    py,
    &[
      PyStdioRead {}.into_py(py),
      PyStdioWrite { is_stdout: true }.into_py(py),
      PyStdioWrite { is_stdout: false }.into_py(py),
    ],
  ))
}

#[pyfunction]
fn stdio_thread_console_set(stdin_fileno: i32, stdout_fileno: i32, stderr_fileno: i32) {
  let dest = stdio::new_console_destination(stdin_fileno, stdout_fileno, stderr_fileno);
  stdio::set_thread_destination(dest)
}

#[pyfunction]
fn stdio_thread_console_clear() {
  stdio::get_destination().console_clear()
}

#[pyclass]
struct PyStdioDestination {
  dest: Arc<stdio::Destination>,
}

#[pymethods]
impl PyStdioDestination {
  #[classmethod]
  fn get_for_thread(_cls: &PyType) -> Self {
    Self {
      dest: stdio::get_destination(),
    }
  }

  fn set_for_thread(&self) {
    stdio::set_thread_destination(self.dest.clone())
  }
}

fn _is_atty(fileno: PyResult<i32>) -> bool {
  if let Ok(fd) = fileno {
    unsafe { libc::isatty(fd) != 0 }
  } else {
    false
  }
}

///
/// A Python file-like that proxies to the `stdio` module, which implements thread-local input.
///
#[pyclass]
struct PyStdioRead {}

#[pymethods]
impl PyStdioRead {
  fn readinto(&self, obj: &PyAny, py: Python) -> PyResult<usize> {
    let py_buffer = PyBuffer::get(obj)?;
    let mut buffer = vec![0; py_buffer.len_bytes()];
    let read = py.allow_threads(|| {
      stdio::get_destination()
        .read_stdin(&mut buffer)
        .map_err(PyException::new_err)
    })?;
    // NB: `as_mut_slice` exposes a `&[Cell<u8>]`, which we can't use directly in `read`. We use
    // `copy_from_slice` instead, which unfortunately involves some extra copying.
    py_buffer.copy_from_slice(py, &buffer)?;
    Ok(read)
  }

  fn fileno(&self) -> PyResult<i32> {
    stdio::get_destination()
      .stdin_as_raw_fd()
      .map_err(PyException::new_err)
  }

  fn isatty(&self) -> bool {
    _is_atty(self.fileno())
  }

  #[getter]
  fn closed(&self) -> bool {
    false
  }

  fn readable(&self) -> bool {
    true
  }

  fn seekable(&self) -> bool {
    false
  }
}

///
/// A Python file-like that proxies to the `stdio` module, which implements thread-local output.
///
#[pyclass]
struct PyStdioWrite {
  is_stdout: bool,
}

#[pymethods]
impl PyStdioWrite {
  fn write(&self, payload: &str, py: Python) {
    py.allow_threads(|| {
      let dest = stdio::get_destination();
      if self.is_stdout {
        dest.write_stdout(payload.as_bytes());
      } else {
        dest.write_stderr(payload.as_bytes());
      }
    });
  }

  fn fileno(&self) -> PyResult<i32> {
    let dest = stdio::get_destination();
    let fd = if self.is_stdout {
      dest.stdout_as_raw_fd()
    } else {
      dest.stderr_as_raw_fd()
    };
    fd.map_err(PyException::new_err)
  }

  fn isatty(&self) -> bool {
    _is_atty(self.fileno())
  }

  fn flush(&self) {
    // All of our destinations are line-buffered.
  }
}
