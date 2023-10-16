// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use pyo3::buffer::PyBuffer;
use pyo3::exceptions::PyException;
use pyo3::prelude::*;

/// A Python file-like that proxies to the `stdio` module, which implements thread-local input.
#[pyclass]
pub struct PyStdioRead;

#[pymethods]
impl PyStdioRead {
    fn isatty(&self) -> bool {
        if let Ok(fd) = self.fileno() {
            unsafe { libc::isatty(fd) != 0 }
        } else {
            false
        }
    }

    fn fileno(&self) -> PyResult<i32> {
        stdio::get_destination()
            .stdin_as_raw_fd()
            .map_err(PyException::new_err)
    }

    fn readinto(&self, obj: &PyAny, py: Python) -> PyResult<usize> {
        let py_buffer = PyBuffer::get(obj)?;
        let mut buffer = vec![0; py_buffer.len_bytes() as usize];
        let read = py
            .allow_threads(|| stdio::get_destination().read_stdin(&mut buffer))
            .map_err(|e| PyException::new_err(e.to_string()))?;
        // NB: `as_mut_slice` exposes a `&[Cell<u8>]`, which we can't use directly in `read`. We use
        // `copy_from_slice` instead, which unfortunately involves some extra copying.
        py_buffer.copy_from_slice(py, &buffer)?;
        Ok(read)
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

/// A Python file-like that proxies to the `stdio` module, which implements thread-local output.
#[pyclass]
pub struct PyStdioWrite {
    pub(crate) is_stdout: bool,
}

#[pymethods]
impl PyStdioWrite {
    fn write(&self, payload: &str, py: Python) {
        py.allow_threads(|| {
            let destination = stdio::get_destination();
            if self.is_stdout {
                destination.write_stdout(payload.as_bytes());
            } else {
                destination.write_stderr(payload.as_bytes());
            }
        });
    }

    fn isatty(&self) -> bool {
        if let Ok(fd) = self.fileno() {
            unsafe { libc::isatty(fd) != 0 }
        } else {
            false
        }
    }

    fn fileno(&self) -> PyResult<i32> {
        let destination = stdio::get_destination();
        let fd = if self.is_stdout {
            destination.stdout_as_raw_fd()
        } else {
            destination.stderr_as_raw_fd()
        };
        fd.map_err(PyException::new_err)
    }

    fn flush(&self) {
        // All of our destinations are line-buffered.
    }
}
