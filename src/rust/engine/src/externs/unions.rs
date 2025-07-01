// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use pyo3::prelude::*;
use std::hash::{Hash, Hasher};

use crate::TypeId;
use crate::externs::is_union;
use fnv::FnvHashMap as HashMap;
use indexmap::IndexSet;
use pyo3::exceptions;
use pyo3::types::PyType;

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

#[pyclass(frozen, str = "UnionMembership({union_rules:?})")]
#[derive(Debug, Default, PartialEq, Eq)]
pub struct UnionMembership {
    pub union_rules: HashMap<TypeId, IndexSet<TypeId>>,
}

#[pymethods]
impl UnionMembership {
    #[staticmethod]
    fn empty() -> Self {
        Self::default()
    }

    #[staticmethod]
    fn from_rules(rules_iter: &Bound<PyAny>) -> PyResult<Self> {
        let mut union_rules: HashMap<TypeId, IndexSet<TypeId>> = HashMap::default();
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

    fn get<'a>(&'a self, union_type: &'a Bound<PyType>) -> PyResult<Vec<Bound<'a, PyType>>> {
        self.__getitem__(union_type)
    }

    fn items(slf: PyRef<Self>) -> Vec<(Bound<PyType>, Vec<Bound<PyType>>)> {
        let mut items = Vec::with_capacity(slf.union_rules.len());
        for (union_type_id, members) in slf.union_rules.iter() {
            let union_type = union_type_id.as_py_type(slf.py());
            let member_types: Vec<_> = members.iter().map(|id| id.as_py_type(slf.py())).collect();
            items.push((union_type, member_types));
        }
        items
    }

    fn __getitem__<'a>(
        &'a self,
        union_type: &'a Bound<PyType>,
    ) -> PyResult<Vec<Bound<'a, PyType>>> {
        let members = self.union_rules.get(&TypeId::new(union_type));
        Ok(members
            .into_iter()
            .flatten()
            .map(|id| id.as_py_type(union_type.py()))
            .collect())
    }

    fn __contains__(&self, union_type: &Bound<PyType>) -> bool {
        self.union_rules.contains_key(&TypeId::new(union_type))
    }

    fn __repr__(&self) -> String {
        self.__pyo3__generated____str__()
    }
}

pub fn register(_py: Python, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<UnionMembership>()?;
    m.add_class::<UnionRule>()?;
    Ok(())
}
