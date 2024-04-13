// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::time::Duration;

use pyo3::exceptions::PyException;
use pyo3::ffi;
use pyo3::prelude::*;

pub fn register(m: &PyModule) -> PyResult<()> {
    m.add_class::<PyExecutor>()?;
    Ok(())
}

// NB: This exists because we need the PyInterpreterState to pass to PyThreadState_New,
// however PyInterpreterState_Get wasn't added until Py 3.9. They vary in implementation, but because
// we don't have any sub-interpreters they should both return the same object.
extern "C" {
    pub fn PyInterpreterState_Main() -> *mut ffi::PyInterpreterState;
}

#[pyclass]
#[derive(Debug)]
pub struct PyExecutor(pub task_executor::Executor);

#[pymethods]
impl PyExecutor {
    #[new]
    fn __new__(core_threads: usize, max_threads: usize) -> PyResult<Self> {
        task_executor::Executor::new_owned(core_threads, max_threads, || {
            // NB: We need a PyThreadState object which lives throughout the lifetime of this thread
            // as the debug trace object is attached to it. Otherwise the PyThreadState is
            // constructed/destroyed with each `with_gil` call (inside PyGILState_Ensure/PyGILState_Release).
            //
            // Constructing (and leaking) a ThreadState object allocates and associates it with the current
            // thread, and the Python runtime won't wipe the trace function between calls.
            // See https://github.com/PyO3/pyo3/issues/2495
            let _ =
                unsafe { ffi::PyThreadState_New(Python::with_gil(|_| PyInterpreterState_Main())) };
            Python::with_gil(|py| {
                let _ = py.eval("__import__('debugpy').debug_this_thread()", None, None);
            });
        })
        .map(PyExecutor)
        .map_err(PyException::new_err)
    }

    /// Returns a clone of the PyExecutor which is disconnected from its parent's lifecycle. Shutdown
    /// of the borrowed clone will have no effect on its parent.
    fn to_borrowed(&self) -> Self {
        PyExecutor(self.0.to_borrowed())
    }

    /// Shut down this executor, waiting for all tasks to exit. Any tasks which have not exited at
    /// the end of the timeout will be leaked.
    fn shutdown(&self, py: Python, duration_secs: f64) {
        py.allow_threads(|| self.0.shutdown(Duration::from_secs_f64(duration_secs)))
    }
}

impl Drop for PyExecutor {
    fn drop(&mut self) {
        if !self.0.is_shutdown() {
            // This can lead to hangs, since `Drop` will run on an arbitrary thread under arbitrary
            // locks. See #18211.
            log::warn!("Executor was not shut down explicitly.");
        }
    }
}
