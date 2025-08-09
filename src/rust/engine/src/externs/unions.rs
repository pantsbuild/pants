// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use crate::TypeId;
use crate::externs::is_union;
use deepsize::DeepSizeOf;
use fnv::FnvBuildHasher;
use indexmap::{IndexMap, IndexSet};
use pyo3::exceptions;
use pyo3::prelude::*;
use pyo3::types::{PyTuple, PyType};
use std::hash::{Hash, Hasher};

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
#[derive(Debug, Default, PartialEq, Eq)]
pub struct UnionMembership {
    pub union_rules: IndexMap<TypeId, IndexSet<TypeId, FnvBuildHasher>, FnvBuildHasher>,
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

        Ok(Self { union_rules })
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
        self.get_members_tuple(union_type)
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
        self.get_members_tuple(union_type).unwrap_or_else(move || {
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
    fn get_members_tuple<'a>(
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

impl Hash for UnionMembership {
    fn hash<H: Hasher>(&self, state: &mut H) {
        for (key, values) in &self.union_rules {
            key.hash(state);
            values.iter().for_each(|el| el.hash(state));
        }
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

pub fn register(_py: Python, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<UnionMembership>()?;
    m.add_class::<UnionRule>()?;
    Ok(())
}
