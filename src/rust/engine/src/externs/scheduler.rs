// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::cell::Cell;
use std::time::Duration;

use pyo3::exceptions::PyException;
use pyo3::ffi;
use pyo3::prelude::*;

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyExecutor>()?;
    Ok(())
}

thread_local! {
    /// This thread's detached `PyThreadState` and the `PyGILState_STATE` returned by the
    /// `PyGILState_Ensure` call that created it.
    static THREAD_STATE: Cell<Option<(*mut ffi::PyThreadState, ffi::PyGILState_STATE)>> =
        const { Cell::new(None) };
}

/// Create a thread state for this thread up front and keep it until `thread_state_destroy`.
///
/// Each `Python::attach` on a thread with no thread state creates one via `PyGILState_Ensure`
/// and destroys it again on release. That resets the debug trace function between calls (see
/// https://github.com/PyO3/pyo3/issues/2495), and on free-threaded builds the teardown is
/// expensive: `PyThreadState_Clear` abandons the thread's mimalloc heaps, which every other
/// thread then pays to reclaim on allocation.
///
/// NB: The state must be created with `PyGILState_Ensure`: the gilstate machinery does not know
/// about states created with `PyThreadState_New`, and would still create and destroy its own on
/// every attach. `PyEval_SaveThread` then detaches, leaving the thread parked without a state
/// attached (which would otherwise block free-threaded stop-the-world pauses).
fn thread_state_create() {
    unsafe {
        let gilstate = ffi::PyGILState_Ensure();
        let tstate = ffi::PyEval_SaveThread();
        THREAD_STATE.set(Some((tstate, gilstate)));
    }
    if std::env::var("PANTS_DEBUG").is_ok() {
        Python::attach(|py| {
            let _ = py.eval(c"__import__('debugpy').debug_this_thread()", None, None);
        });
    }
}

/// Release the thread state created by `thread_state_create`. Tokio recycles blocking-pool
/// threads after an idle timeout, so thread states must die with their threads or they
/// accumulate for the life of the process. Re-attaching and then releasing the last gilstate
/// reference has CPython clear and delete the state.
fn thread_state_destroy() {
    if let Some((tstate, gilstate)) = THREAD_STATE.take() {
        unsafe {
            if ffi::Py_IsInitialized() != 0 {
                ffi::PyEval_RestoreThread(tstate);
                ffi::PyGILState_Release(gilstate);
            }
        }
    }
}

#[pyclass]
#[derive(Debug)]
pub struct PyExecutor(pub task_executor::Executor);

#[pymethods]
impl PyExecutor {
    #[new]
    fn __new__(core_threads: usize, max_threads: usize) -> PyResult<Self> {
        task_executor::Executor::new_owned(
            core_threads,
            max_threads,
            thread_state_create,
            thread_state_destroy,
        )
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
        py.detach(|| self.0.shutdown(Duration::from_secs_f64(duration_secs)))
    }
}

impl Drop for PyExecutor {
    fn drop(&mut self) {
        if self.0.is_shutdown() {
            return;
        }
        log::warn!("Executor was not shut down explicitly.");
        // Dropping the Runtime joins its threads, and each thread attaches to Python in
        // `thread_state_destroy` before exiting. `Drop` runs attached (via garbage collection),
        // so shut down with this thread detached or the joins deadlock on the GIL.
        //
        // Shutting down from within a runtime would panic, and attaching from a detached thread
        // acquires the GIL, which can deadlock under arbitrary Python-side locks (see #18211):
        // leak it in both cases.
        //
        // When already attached, `Python::attach` acquires nothing and `py.detach` only releases.
        //
        // SAFETY: `PyGILState_Check` may be called from any thread at any time.
        if tokio::runtime::Handle::try_current().is_err() && unsafe { ffi::PyGILState_Check() } == 1
        {
            Python::attach(|py| py.detach(|| self.0.shutdown(Duration::from_secs(3))));
        }
    }
}
