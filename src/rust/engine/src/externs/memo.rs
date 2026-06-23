// Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashMap;
use std::sync::Arc;

use once_cell::sync::OnceCell;
use parking_lot::RwLock;
use pyo3::prelude::*;

use crate::python::Key;

#[pyclass(frozen, module = "pants.engine.internals.native_engine")]
pub struct LockMap {
    map: RwLock<HashMap<Key, Arc<OnceCell<Py<PyAny>>>>>,
}

#[pymethods]
impl LockMap {
    #[new]
    fn __new__() -> Self {
        Self {
            map: RwLock::new(HashMap::new()),
        }
    }

    fn get_or_insert(&self, py: Python<'_>, key: Key, compute: Py<PyAny>) -> PyResult<Py<PyAny>> {
        py.detach(move || self.get_or_insert_with(key, || Python::attach(|py| compute.call0(py))))
    }

    fn put(&self, py: Python<'_>, key: Key, value: Py<PyAny>) {
        py.detach(move || {
            let cell = OnceCell::new();
            let _ = cell.set(value);
            self.map.write().insert(key, Arc::new(cell));
        });
    }

    fn forget(&self, py: Python<'_>, key: Key) {
        py.detach(move || {
            self.map.write().remove(&key);
        });
    }

    fn clear(&self, py: Python<'_>) {
        py.detach(|| {
            self.map.write().clear();
        });
    }
}

impl LockMap {
    fn cell_for(&self, key: Key) -> Arc<OnceCell<Py<PyAny>>> {
        if let Some(cell) = self.map.read().get(&key).cloned() {
            return cell;
        }

        self.map
            .write()
            .entry(key)
            .or_insert_with(|| Arc::new(OnceCell::new()))
            .clone()
    }

    fn get_or_insert_with(
        &self,
        key: Key,
        compute: impl FnOnce() -> PyResult<Py<PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        let cell = self.cell_for(key);
        let value = cell.get_or_try_init(compute)?;
        Python::attach(|py| Ok(value.clone_ref(py)))
    }
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<LockMap>()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::LockMap;
    use crate::python::Key;
    use pyo3::exceptions::PyValueError;
    use pyo3::prelude::*;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::{Arc, Barrier, Condvar, Mutex};
    use std::thread;
    use std::time::Duration;

    fn key(py: Python<'_>, value: i64) -> Key {
        value
            .into_pyobject(py)
            .unwrap()
            .into_any()
            .extract()
            .unwrap()
    }

    fn py_value(py: Python<'_>, value: i64) -> Py<PyAny> {
        value.into_pyobject(py).unwrap().into_any().unbind()
    }

    fn i64_value(value: Py<PyAny>) -> i64 {
        Python::attach(|py| value.extract(py).unwrap())
    }

    fn wait_for_all(started: &Arc<(Mutex<usize>, Condvar)>, total: usize) {
        let (lock, cvar) = &**started;
        let mut count = lock.lock().unwrap();
        *count += 1;
        cvar.notify_all();
        while *count < total {
            let result = cvar.wait_timeout(count, Duration::from_secs(5)).unwrap();
            count = result.0;
            assert!(
                !result.1.timed_out(),
                "timed out waiting for concurrent initialization"
            );
        }
    }

    #[test]
    fn same_key_concurrent_calls_initialize_once() {
        Python::initialize();

        let cache = Arc::new(LockMap::__new__());
        let key = Python::attach(|py| key(py, 1));
        let ready = Arc::new(Barrier::new(8));
        let calls = Arc::new(AtomicUsize::new(0));

        let handles: Vec<_> = (0..8)
            .map(|_| {
                let cache = Arc::clone(&cache);
                let key = key.clone();
                let ready = Arc::clone(&ready);
                let calls = Arc::clone(&calls);
                thread::spawn(move || {
                    ready.wait();
                    let value = cache
                        .get_or_insert_with(key, || {
                            calls.fetch_add(1, Ordering::SeqCst);
                            thread::sleep(Duration::from_millis(50));
                            Python::attach(|py| Ok(py_value(py, 99)))
                        })
                        .unwrap();
                    i64_value(value)
                })
            })
            .collect();

        let results: Vec<_> = handles
            .into_iter()
            .map(|handle| handle.join().unwrap())
            .collect();
        assert_eq!(vec![99; 8], results);
        assert_eq!(1, calls.load(Ordering::SeqCst));
    }

    #[test]
    fn different_keys_initialize_independently() {
        Python::initialize();

        let cache = Arc::new(LockMap::__new__());
        let started = Arc::new((Mutex::new(0), Condvar::new()));
        let keys: Vec<_> = Python::attach(|py| (0..8).map(|value| key(py, value)).collect());

        let handles: Vec<_> = keys
            .into_iter()
            .enumerate()
            .map(|(value, key)| {
                let cache = Arc::clone(&cache);
                let started = Arc::clone(&started);
                thread::spawn(move || {
                    let value = cache
                        .get_or_insert_with(key, || {
                            wait_for_all(&started, 8);
                            Python::attach(|py| Ok(py_value(py, value as i64)))
                        })
                        .unwrap();
                    i64_value(value)
                })
            })
            .collect();

        let results: Vec<_> = handles
            .into_iter()
            .map(|handle| handle.join().unwrap())
            .collect();
        assert_eq!((0..8).collect::<Vec<_>>(), results);
    }

    #[test]
    fn failed_initialization_is_not_cached() {
        Python::initialize();

        let cache = LockMap::__new__();
        let key = Python::attach(|py| key(py, 1));
        let calls = AtomicUsize::new(0);

        assert!(
            cache
                .get_or_insert_with(key.clone(), || {
                    calls.fetch_add(1, Ordering::SeqCst);
                    Err(PyValueError::new_err("bad"))
                })
                .is_err()
        );

        let value = cache
            .get_or_insert_with(key, || {
                calls.fetch_add(1, Ordering::SeqCst);
                Python::attach(|py| Ok(py_value(py, 42)))
            })
            .unwrap();

        assert_eq!(42, i64_value(value));
        assert_eq!(2, calls.load(Ordering::SeqCst));
    }

    #[test]
    fn put_forget_and_clear() {
        Python::initialize();

        let cache = LockMap::__new__();
        let key = Python::attach(|py| key(py, 1));
        let calls = AtomicUsize::new(0);

        Python::attach(|py| cache.put(py, key.clone(), py_value(py, 10)));
        let value = cache
            .get_or_insert_with(key.clone(), || {
                calls.fetch_add(1, Ordering::SeqCst);
                Python::attach(|py| Ok(py_value(py, 20)))
            })
            .unwrap();
        assert_eq!(10, i64_value(value));
        assert_eq!(0, calls.load(Ordering::SeqCst));

        Python::attach(|py| cache.forget(py, key.clone()));
        let value = cache
            .get_or_insert_with(key.clone(), || {
                calls.fetch_add(1, Ordering::SeqCst);
                Python::attach(|py| Ok(py_value(py, 20)))
            })
            .unwrap();
        assert_eq!(20, i64_value(value));
        assert_eq!(1, calls.load(Ordering::SeqCst));

        Python::attach(|py| cache.put(py, key.clone(), py_value(py, 30)));
        Python::attach(|py| cache.clear(py));
        let value = cache
            .get_or_insert_with(key, || {
                calls.fetch_add(1, Ordering::SeqCst);
                Python::attach(|py| Ok(py_value(py, 40)))
            })
            .unwrap();
        assert_eq!(40, i64_value(value));
        assert_eq!(2, calls.load(Ordering::SeqCst));
    }
}
