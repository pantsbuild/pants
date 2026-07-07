// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::collections::HashMap;
use std::hash::{Hash, Hasher};
use std::sync::OnceLock;

use crate::TypeId;
use crate::externs::is_union;
use deepsize::DeepSizeOf;
use fnv::{FnvBuildHasher, FnvHasher};
use indexmap::{IndexMap, IndexSet};
use parking_lot::Mutex;
use pyo3::exceptions::{self, PyValueError};
use pyo3::intern;
use pyo3::prelude::*;
use pyo3::pybacked::PyBackedStr;
use pyo3::types::{PyDict, PyTuple, PyType};

#[pyclass(
    frozen,
    hash,
    eq,
    str = "UnionRule(union_base={union_base}, union_member={union_member})"
)]
#[derive(Debug)]
pub struct UnionRule {
    #[pyo3(get)]
    pub union_base: Py<PyType>,
    #[pyo3(get)]
    pub union_member: Py<PyType>,
}

impl Hash for UnionRule {
    fn hash<H: Hasher>(&self, state: &mut H) {
        TypeId::from_owned(&self.union_base).hash(state);
        TypeId::from_owned(&self.union_member).hash(state);
    }
}

impl PartialEq for UnionRule {
    fn eq(&self, other: &Self) -> bool {
        TypeId::from_owned(&self.union_base).eq(&TypeId::from_owned(&other.union_base))
            && TypeId::from_owned(&self.union_member).eq(&TypeId::from_owned(&other.union_member))
    }
}

#[pymethods]
impl UnionRule {
    #[new]
    fn __new__(union_base: Py<PyType>, union_member: Py<PyType>, py: Python) -> PyResult<Self> {
        Self::validate_arguments(union_base.bind(py), union_member.bind(py), py)?;
        Ok(Self {
            union_base,
            union_member,
        })
    }

    fn __repr__(&self) -> String {
        self.__pyo3__generated____str__()
    }
}
impl UnionRule {
    fn validate_arguments(
        union_base: &Bound<'_, PyType>,
        union_member: &Bound<'_, PyType>,
        py: Python,
    ) -> PyResult<()> {
        if !is_union(py, union_base)? {
            let mut msg = format!(
                "The first argument must be a class annotated with @union (from pants.engine.unions), but was {union_base}."
            );
            if is_union(py, union_member)? {
                msg.push_str(
                    "\n\nHowever, the second argument was annotated with `@union`. Did you switch the first and second arguments to `UnionRule()`?"
                )
            }
            return Err(PyErr::new::<exceptions::PyValueError, _>(msg));
        }
        Ok(())
    }
}

#[pyclass(frozen, eq, hash, str = "UnionMembership({union_rules:?})")]
#[derive(Debug, Default)]
pub struct UnionMembership {
    pub union_rules: IndexMap<TypeId, IndexSet<TypeId, FnvBuildHasher>, FnvBuildHasher>,
    cached_hash: OnceLock<u64>,
}

#[pymethods]
impl UnionMembership {
    #[staticmethod]
    fn empty() -> Self {
        Self::default()
    }

    #[staticmethod]
    fn from_rules(rules_iter: &Bound<PyAny>) -> PyResult<Self> {
        let mut union_rules: IndexMap<TypeId, IndexSet<TypeId, _>, _> = IndexMap::default();
        for rule_obj in rules_iter.try_iter()? {
            let rule: Bound<UnionRule> = rule_obj?.extract()?;
            let rule_ref = rule.get();
            let base = &rule_ref.union_base;
            let member = &rule_ref.union_member;
            union_rules
                .entry(TypeId::from_owned(base))
                .or_default()
                .insert(TypeId::from_owned(member));
        }

        Ok(Self {
            union_rules,
            cached_hash: OnceLock::new(),
        })
    }

    fn is_member(
        &self,
        union_type: &Bound<PyType>,
        putative_member: &Bound<PyType>,
    ) -> PyResult<bool> {
        self.union_rules
            .get(&TypeId::new(union_type))
            .map(|members| members.contains(&TypeId::new(putative_member)))
            .ok_or_else(|| {
                exceptions::PyTypeError::new_err(format!(
                    "Not a registered union type: {union_type}"
                ))
            })
    }

    fn has_members(&self, union_type: &Bound<PyType>) -> bool {
        self.union_rules.contains_key(&TypeId::new(union_type))
    }

    fn get<'a>(&self, union_type: &'a Bound<PyType>) -> PyResult<Bound<'a, PyTuple>> {
        self.get_members(union_type)
            .unwrap_or_else(|| Ok(PyTuple::empty(union_type.py())))
    }

    fn items(slf: PyRef<Self>) -> PyResult<Bound<PyTuple>> {
        let into_pytype = |type_id: &TypeId| type_id.as_py_type(slf.py());
        PyTuple::new(
            slf.py(),
            slf.union_rules
                .iter()
                .map(|(union_type_id, members)| {
                    PyTuple::new(slf.py(), members.iter().map(into_pytype))
                        .map(|members| (into_pytype(union_type_id), members))
                })
                .collect::<PyResult<Vec<_>>>()?,
        )
    }

    fn __getitem__<'a>(&self, union_type: &'a Bound<PyType>) -> PyResult<Bound<'a, PyTuple>> {
        self.get_members(union_type).unwrap_or_else(move || {
            Err(exceptions::PyIndexError::new_err(format!(
                "'{}' is not registered as a union.",
                TypeId::new(union_type)
            )))
        })
    }

    fn __contains__(&self, union_type: &Bound<PyType>) -> bool {
        self.union_rules.contains_key(&TypeId::new(union_type))
    }

    fn __repr__(&self) -> String {
        self.__pyo3__generated____str__()
    }
}

impl UnionMembership {
    pub fn get_members<'a>(
        &self,
        union_type: &'a Bound<PyType>,
    ) -> Option<PyResult<Bound<'a, PyTuple>>> {
        self.union_rules
            .get(&TypeId::new(union_type))
            .map(|members| {
                PyTuple::new(
                    union_type.py(),
                    members.into_iter().map(|id| id.as_py_type(union_type.py())),
                )
            })
    }
}

impl PartialEq for UnionMembership {
    fn eq(&self, other: &Self) -> bool {
        self.union_rules == other.union_rules
    }
}

impl Eq for UnionMembership {}

impl UnionMembership {
    // XOR over the unique `(base, member)` pairs, so the hash is order-insensitive like the equality.
    fn compute_hash(&self) -> u64 {
        self.union_rules.iter().fold(0_u64, |acc, (base, members)| {
            members.iter().fold(acc, |acc, member| {
                let mut h = FnvHasher::default();
                base.hash(&mut h);
                member.hash(&mut h);
                acc ^ h.finish()
            })
        })
    }
}

impl Hash for UnionMembership {
    fn hash<H: Hasher>(&self, state: &mut H) {
        state.write_u64(*self.cached_hash.get_or_init(|| self.compute_hash()));
    }
}

impl DeepSizeOf for UnionMembership {
    fn deep_size_of_children(&self, _: &mut deepsize::Context) -> usize {
        let map_size: usize = self.union_rules.capacity()
            * (size_of::<(usize, TypeId, IndexSet<TypeId>)>() + size_of::<usize>());
        map_size
            + self
                .union_rules
                .iter()
                .map(|(key, values)| {
                    key.deep_size_of()
                        + (values.iter().map(DeepSizeOf::deep_size_of).sum::<usize>()
                            + values.capacity()
                                * (size_of::<(usize, TypeId, ())>() + size_of::<usize>()))
                })
                .sum::<usize>()
    }
}

/// Backs `Target.PluginField`: accessing it from a target subclass returns a distinct `@union`
/// type per subclass (as `@distinct_union_type_per_subclass` does in Python), so plugin fields
/// registered against one target type don't leak to others.
#[pyclass(frozen, module = "pants.engine.internals.native_engine")]
pub struct PluginFieldDescriptor {
    base_class: Py<PyType>,
    cache: Mutex<HashMap<TypeId, Py<PyType>>>,
}

impl PluginFieldDescriptor {
    pub fn new(base_class: Py<PyType>) -> Self {
        Self {
            base_class,
            cache: Mutex::new(HashMap::new()),
        }
    }

    fn make_type_copy(&self, objtype: &Bound<'_, PyType>, py: Python) -> PyResult<Py<PyType>> {
        let base = self.base_class.bind(py);
        let name = base.getattr(intern!(py, "__name__"))?;
        let bases = base.getattr(intern!(py, "__bases__"))?;

        let new_dict = PyDict::new(py);
        let base_dict = base.getattr(intern!(py, "__dict__"))?;
        for key in base_dict.try_iter()? {
            let key = key?;
            let value = base_dict.get_item(&key)?;
            new_dict.set_item(&key, &value)?;
        }

        let objtype_qualname: PyBackedStr =
            objtype.getattr(intern!(py, "__qualname__"))?.extract()?;
        let base_name: PyBackedStr = name.extract()?;
        new_dict.set_item(
            intern!(py, "__qualname__"),
            format!("{}.{}", &*objtype_qualname, &*base_name),
        )?;

        let type_metaclass = py.get_type::<PyType>();
        let new_type: Bound<'_, PyType> = type_metaclass
            .call1((&name, &bases, &new_dict))?
            .extract()?;

        new_type.setattr(intern!(py, "_is_union_for"), &new_type)?;
        let in_scope_types = base
            .getattr(intern!(py, "_union_in_scope_types"))
            .ok()
            .filter(|v| !v.is_none())
            .unwrap_or_else(|| PyTuple::empty(py).into_any());
        new_type.setattr(intern!(py, "_union_in_scope_types"), in_scope_types)?;

        Ok(new_type.unbind())
    }
}

#[pymethods]
impl PluginFieldDescriptor {
    fn __get__(
        &self,
        obj: Option<&Bound<'_, PyAny>>,
        objtype: Option<&Bound<'_, PyType>>,
        py: Python,
    ) -> PyResult<Py<PyType>> {
        let objtype = match objtype {
            Some(t) => t.clone(),
            None => match obj {
                Some(o) => o.get_type(),
                None => return Err(PyValueError::new_err("descriptor needs an object or type")),
            },
        };
        let type_id = TypeId::new(&objtype);

        {
            let cache = self.cache.lock();
            if let Some(cached) = cache.get(&type_id) {
                return Ok(cached.clone_ref(py));
            }
        }

        let new_type = self.make_type_copy(&objtype, py)?;

        let mut cache = self.cache.lock();
        cache.insert(type_id, new_type.clone_ref(py));
        Ok(new_type)
    }
}

pub fn register(_py: Python, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<UnionMembership>()?;
    m.add_class::<UnionRule>()?;
    m.add_class::<PluginFieldDescriptor>()?;
    Ok(())
}
