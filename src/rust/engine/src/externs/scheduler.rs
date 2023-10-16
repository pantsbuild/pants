// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

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
#[derive(Debug, Clone)]
pub struct PyExecutor(pub task_executor::Executor);

#[pymethods]
impl PyExecutor {
    #[new]
    fn __new__(core_threads: usize, max_threads: usize) -> PyResult<Self> {
        task_executor::Executor::global(core_threads, max_threads, || {
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
}
