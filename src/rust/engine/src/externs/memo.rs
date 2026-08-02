// Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashMap;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

use once_cell::sync::OnceCell;
use parking_lot::RwLock;
use pyo3::gc::{PyTraverseError, PyVisit};
use pyo3::intern;
use pyo3::prelude::*;
use pyo3::types::PyDict;

/// A per-decorated-function memoization cache with exactly-once computation per key.
///
/// Keys are arbitrary hashable Python objects, interned to a local integer id via a dict owned by
/// this `LockedMap`. The engine's global `Interns` table is deliberately not used: it never evicts,
/// while memo keys must be released by `forget`/`clear`/property `del` (a `per_instance` key holds
/// a strong reference to `self`). Ids are assigned with `dict.setdefault`, a single dict operation
/// and so atomic on free-threaded builds; a lost race wastes only an integer.
#[pyclass(frozen, generic, module = "pants.engine.internals.native_engine")]
pub struct LockedMap {
    ids: Py<PyDict>,
    /// `ids.setdefault`, bound once: the hot path calls it per memoized invocation.
    ids_setdefault: Py<PyAny>,
    next_id: AtomicU64,
    map: RwLock<HashMap<u64, Arc<OnceCell<Py<PyAny>>>>>,
}

#[pymethods]
impl LockedMap {
    #[new]
    fn __new__(py: Python<'_>) -> PyResult<Self> {
        let ids = PyDict::new(py);
        let ids_setdefault = ids.getattr(intern!(py, "setdefault"))?.unbind();
        Ok(Self {
            ids: ids.unbind(),
            ids_setdefault,
            next_id: AtomicU64::new(0),
            map: RwLock::new(HashMap::new()),
        })
    }

    fn get_or_insert(
        &self,
        py: Python<'_>,
        key: Py<PyAny>,
        compute: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        let id = self.intern(py, &key)?;
        let value = py.detach(move || {
            self.get_or_insert_with(id, || Python::attach(|py| compute.call0(py)))
        })?;
        self.reconcile(py, &key, id);
        Ok(value)
    }

    fn put(&self, py: Python<'_>, key: Py<PyAny>, value: Py<PyAny>) -> PyResult<()> {
        let id = self.intern(py, &key)?;
        py.detach(move || {
            let cell = OnceCell::new();
            let _ = cell.set(value);
            self.map.write().insert(id, Arc::new(cell));
        });
        self.reconcile(py, &key, id);
        Ok(())
    }

    fn forget(&self, py: Python<'_>, key: Py<PyAny>) -> PyResult<()> {
        let id: Option<u64> = self
            .ids
            .bind(py)
            .call_method1(intern!(py, "pop"), (key, py.None()))?
            .extract()?;
        if let Some(id) = id {
            py.detach(move || {
                self.map.write().remove(&id);
            });
        }
        Ok(())
    }

    fn clear(&self, py: Python<'_>) -> PyResult<()> {
        self.ids.bind(py).call_method0(intern!(py, "clear"))?;
        py.detach(|| {
            self.map.write().clear();
        });
        Ok(())
    }

    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.ids)?;
        visit.call(&self.ids_setdefault)?;
        // gc must not block: skip the values if a writer holds the lock this pass.
        if let Some(map) = self.map.try_read() {
            for cell in map.values() {
                if let Some(value) = cell.get() {
                    visit.call(value)?;
                }
            }
        }
        Ok(())
    }

    fn __clear__(&self) {
        // The id dict is its own gc-tracked object (broken by its tp_clear); ours is the values.
        self.map.write().clear();
    }
}

impl LockedMap {
    /// Return the stable local id for `key`, assigning the next id if unseen. `setdefault` makes
    /// the check-and-assign a single atomic dict operation.
    fn intern(&self, py: Python<'_>, key: &Py<PyAny>) -> PyResult<u64> {
        let candidate = self.next_id.fetch_add(1, Ordering::Relaxed);
        self.ids_setdefault
            .bind(py)
            .call1((key, candidate))?
            .extract()
    }

    /// A writer's intern-then-populate is not atomic against `forget`/`clear`, which could strand
    /// a just-populated entry under an id no longer reachable from `ids`. After populating,
    /// re-assert the binding: if the key still (or again) maps to our id, the entry is reachable
    /// and a later `forget` can release it. If it now maps to a different id (a concurrent
    /// forget-then-reintern won), drop our entry rather than leak it.
    fn reconcile(&self, py: Python<'_>, key: &Py<PyAny>, id: u64) {
        let current: Option<u64> = self.intern(py, key).ok().filter(|current| *current != id);
        if current.is_some() {
            py.detach(|| {
                self.map.write().remove(&id);
            });
        }
    }

    fn get_or_insert_with(
        &self,
        id: u64,
        compute: impl FnOnce() -> PyResult<Py<PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        let cell = self.cell_for(id);
        let value = cell.get_or_try_init(compute)?;
        Python::attach(|py| Ok(value.clone_ref(py)))
    }

    fn cell_for(&self, id: u64) -> Arc<OnceCell<Py<PyAny>>> {
        if let Some(cell) = self.map.read().get(&id).cloned() {
            return cell;
        }

        self.map
            .write()
            .entry(id)
            .or_insert_with(|| Arc::new(OnceCell::new()))
            .clone()
    }
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<LockedMap>()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::LockedMap;
    use pyo3::exceptions::PyValueError;
    use pyo3::prelude::*;
    use pyo3::types::PyDictMethods;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::{Arc, Barrier, Condvar, Mutex};
    use std::thread;
    use std::time::Duration;

    fn new_locked_map() -> LockedMap {
        Python::attach(|py| LockedMap::__new__(py).unwrap())
    }

    fn key(py: Python<'_>, value: i64) -> Py<PyAny> {
        value.into_pyobject(py).unwrap().into_any().unbind()
    }

    fn py_value(py: Python<'_>, value: i64) -> Py<PyAny> {
        value.into_pyobject(py).unwrap().into_any().unbind()
    }

    fn i64_value(value: Py<PyAny>) -> i64 {
        Python::attach(|py| value.extract(py).unwrap())
    }

    fn intern(cache: &LockedMap, key: &Py<PyAny>) -> u64 {
        Python::attach(|py| cache.intern(py, key).unwrap())
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

        let cache = Arc::new(new_locked_map());
        let key = Python::attach(|py| key(py, 1));
        let ready = Arc::new(Barrier::new(8));
        let calls = Arc::new(AtomicUsize::new(0));

        let handles: Vec<_> = (0..8)
            .map(|_| {
                let cache = Arc::clone(&cache);
                let key = Python::attach(|py| key.clone_ref(py));
                let ready = Arc::clone(&ready);
                let calls = Arc::clone(&calls);
                thread::spawn(move || {
                    ready.wait();
                    // Each thread interns independently, covering the concurrent id-assignment
                    // path as well as the once-only computation.
                    let id = intern(&cache, &key);
                    let value = cache
                        .get_or_insert_with(id, || {
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

        let cache = Arc::new(new_locked_map());
        let started = Arc::new((Mutex::new(0), Condvar::new()));
        let keys: Vec<_> = Python::attach(|py| (0..8).map(|value| key(py, value)).collect());

        let handles: Vec<_> = keys
            .into_iter()
            .enumerate()
            .map(|(value, key)| {
                let cache = Arc::clone(&cache);
                let started = Arc::clone(&started);
                thread::spawn(move || {
                    let id = intern(&cache, &key);
                    let value = cache
                        .get_or_insert_with(id, || {
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

        let cache = new_locked_map();
        let key = Python::attach(|py| key(py, 1));
        let calls = AtomicUsize::new(0);

        let id = intern(&cache, &key);
        assert!(
            cache
                .get_or_insert_with(id, || {
                    calls.fetch_add(1, Ordering::SeqCst);
                    Err(PyValueError::new_err("bad"))
                })
                .is_err()
        );

        let value = cache
            .get_or_insert_with(id, || {
                calls.fetch_add(1, Ordering::SeqCst);
                Python::attach(|py| Ok(py_value(py, 42)))
            })
            .unwrap();

        assert_eq!(42, i64_value(value));
        assert_eq!(2, calls.load(Ordering::SeqCst));
    }

    #[test]
    fn equal_keys_share_an_id() {
        Python::initialize();

        let cache = new_locked_map();
        // Equal-but-not-identical keys (Python smallint caching is bypassed via tuples).
        let (a, b) = Python::attach(|py| {
            let a = (1_i64, "x").into_pyobject(py).unwrap().into_any().unbind();
            let b = (1_i64, "x").into_pyobject(py).unwrap().into_any().unbind();
            (a, b)
        });
        assert_eq!(intern(&cache, &a), intern(&cache, &b));
    }

    #[test]
    fn put_forget_and_clear() {
        Python::initialize();

        let cache = new_locked_map();
        let key = Python::attach(|py| key(py, 1));
        let calls = AtomicUsize::new(0);

        Python::attach(|py| cache.put(py, key.clone_ref(py), py_value(py, 10)).unwrap());
        let id = intern(&cache, &key);
        let value = cache
            .get_or_insert_with(id, || {
                calls.fetch_add(1, Ordering::SeqCst);
                Python::attach(|py| Ok(py_value(py, 20)))
            })
            .unwrap();
        assert_eq!(10, i64_value(value));
        assert_eq!(0, calls.load(Ordering::SeqCst));

        Python::attach(|py| cache.forget(py, key.clone_ref(py)).unwrap());
        let id = intern(&cache, &key);
        let value = cache
            .get_or_insert_with(id, || {
                calls.fetch_add(1, Ordering::SeqCst);
                Python::attach(|py| Ok(py_value(py, 20)))
            })
            .unwrap();
        assert_eq!(20, i64_value(value));
        assert_eq!(1, calls.load(Ordering::SeqCst));

        Python::attach(|py| cache.put(py, key.clone_ref(py), py_value(py, 30)).unwrap());
        Python::attach(|py| cache.clear(py).unwrap());
        let id = intern(&cache, &key);
        let value = cache
            .get_or_insert_with(id, || {
                calls.fetch_add(1, Ordering::SeqCst);
                Python::attach(|py| Ok(py_value(py, 40)))
            })
            .unwrap();
        assert_eq!(40, i64_value(value));
        assert_eq!(2, calls.load(Ordering::SeqCst));
    }

    #[test]
    fn reconcile_drops_entry_when_forget_won() {
        Python::initialize();

        let cache = new_locked_map();
        let key = Python::attach(|py| key(py, 1));

        // Writer interned id, then a concurrent forget popped the binding before the writer
        // populated the map: reconcile must not leave the entry stranded under the dead id.
        let id = intern(&cache, &key);
        Python::attach(|py| cache.forget(py, key.clone_ref(py)).unwrap());
        cache
            .get_or_insert_with(id, || Python::attach(|py| Ok(py_value(py, 7))))
            .unwrap();
        Python::attach(|py| cache.reconcile(py, &key, id));
        assert!(!cache.map.read().contains_key(&id));

        // No interference: reconcile keeps the entry when the binding still points at our id.
        let id = intern(&cache, &key);
        cache
            .get_or_insert_with(id, || Python::attach(|py| Ok(py_value(py, 8))))
            .unwrap();
        Python::attach(|py| cache.reconcile(py, &key, id));
        assert!(cache.map.read().contains_key(&id));
    }

    #[test]
    fn forget_and_clear_release_keys() {
        Python::initialize();

        let cache = new_locked_map();
        let (key_a, key_b) = Python::attach(|py| (key(py, 1), key(py, 2)));

        Python::attach(|py| {
            cache
                .put(py, key_a.clone_ref(py), py_value(py, 10))
                .unwrap();
            cache
                .put(py, key_b.clone_ref(py), py_value(py, 20))
                .unwrap();
            assert_eq!(2, cache.ids.bind(py).len());

            cache.forget(py, key_a.clone_ref(py)).unwrap();
            assert_eq!(1, cache.ids.bind(py).len());

            cache.clear(py).unwrap();
            assert_eq!(0, cache.ids.bind(py).len());
        });
        assert!(cache.map.read().is_empty());
    }
}
