// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
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
// File-specific allowances to silence internal warnings of `py_class!`.
#![allow(
  unused_braces,
  clippy::manual_strip,
  clippy::used_underscore_binding,
  clippy::transmute_ptr_to_ptr,
  clippy::zero_ptr
)]
// TODO: False positive for |py| in py_class!.
#![allow(unused_variables)]

use cpython::buffer::PyBuffer;
use cpython::{exc, py_class, PyErr, PyObject, PyResult, Python};

///
/// Data members and `create_instance` methods are module-private by default, so we expose them
/// with public top-level functions.
///
/// TODO: See https://github.com/dgrunwald/rust-cpython/issues/242
///

///
/// A Python file-like that proxies to the `stdio` module, which implements thread-local input.
///
pub fn py_stdio_read() -> PyResult<PyStdioRead> {
  let gil = Python::acquire_gil();
  PyStdioRead::create_instance(gil.python())
}

py_class!(pub class PyStdioRead |py| {
    def isatty(&self) -> PyResult<bool> {
      if let Ok(fd) = self.fileno(py) {
        Ok(unsafe { libc::isatty(fd) != 0 })
      } else {
        Ok(false)
      }
    }

    def fileno(&self) -> PyResult<i32> {
      stdio::get_destination().stdin_as_raw_fd().map_err(|e| PyErr::new::<exc::Exception, _>(py, (e,)))
    }

    def readinto(&self, obj: PyObject) -> PyResult<usize> {
      let py_buffer = PyBuffer::get(py, &obj)?;
      let mut buffer = vec![0; py_buffer.len_bytes() as usize];
      let read = py.allow_threads(|| {
        stdio::get_destination().read_stdin(&mut buffer)
      }).map_err(|e| PyErr::new::<exc::Exception, _>(py, (e.to_string(),)))?;
      // NB: `as_mut_slice` exposes a `&[Cell<u8>]`, which we can't use directly in `read`. We use
      // `copy_from_slice` instead, which unfortunately involves some extra copying.
      py_buffer.copy_from_slice(py, &buffer)?;
      Ok(read)
    }

    @property
    def closed(&self) -> PyResult<bool> {
      Ok(false)
    }

    def readable(&self) -> PyResult<bool> {
      Ok(true)
    }

    def seekable(&self) -> PyResult<bool> {
      Ok(false)
    }
});

///
/// A Python file-like that proxies to the `stdio` module, which implements thread-local output.
///
pub fn py_stdio_write(is_stdout: bool) -> PyResult<PyStdioWrite> {
  let gil = Python::acquire_gil();
  PyStdioWrite::create_instance(gil.python(), is_stdout)
}

py_class!(pub class PyStdioWrite |py| {
    data is_stdout: bool;

    def write(&self, payload: &str) -> PyResult<PyObject> {
      let is_stdout = *self.is_stdout(py);
      py.allow_threads(|| {
        let destination = stdio::get_destination();
        if is_stdout {
          destination.write_stdout(payload.as_bytes());
        } else {
          destination.write_stderr(payload.as_bytes());
        }
      });
      Ok(Python::None(py))
    }

    def isatty(&self) -> PyResult<bool> {
      if let Ok(fd) = self.fileno(py) {
        Ok(unsafe { libc::isatty(fd) != 0 })
      } else {
        Ok(false)
      }
    }

    def fileno(&self) -> PyResult<i32> {
      let destination = stdio::get_destination();
      let fd = if *self.is_stdout(py) {
        destination.stdout_as_raw_fd()
      } else {
        destination.stderr_as_raw_fd()
      };
      fd.map_err(|e| PyErr::new::<exc::Exception, _>(py, (e,)))
    }

    def flush(&self) -> PyResult<PyObject> {
        // All of our destinations are line-buffered.
        Ok(Python::None(py))
    }
});
