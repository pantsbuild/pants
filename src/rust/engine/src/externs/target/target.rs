// Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::fmt::Write;
use std::hash::{Hash, Hasher};
use std::sync::OnceLock;

use fnv::{FnvHashMap, FnvHasher};

use parking_lot::Mutex;
use pyo3::basic::CompareOp;
use pyo3::exceptions::{PyKeyError, PyValueError};
use pyo3::prelude::*;
use pyo3::pybacked::PyBackedStr;
use pyo3::types::{PyDict, PyList, PySet, PyTuple, PyType};
use pyo3::{IntoPyObjectExt, intern};

use crate::TypeId;
use crate::externs::address::Address;
use crate::externs::frozen_ordered_set::FrozenOrderedSet;
use crate::externs::frozendict::FrozenDict;
use crate::externs::unions::{PluginFieldDescriptor, UnionMembership, UnionRule};
use crate::python::PyComparedBool;

use super::util::{
    NoFieldValue, PyReprList, combine_hashes, import_attr, import_target_attr, import_type,
    raise_invalid_field,
};

static WARN_OR_ERROR: OnceLock<Py<PyAny>> = OnceLock::new();
static INVALID_TARGET_EXCEPTION: OnceLock<Py<PyAny>> = OnceLock::new();
static TARGET_GENERATOR_CLS: OnceLock<Py<PyType>> = OnceLock::new();

struct CacheKey {
    cls: TypeId,
    union_membership: Option<Py<UnionMembership>>,
}

impl PartialEq for CacheKey {
    fn eq(&self, other: &Self) -> bool {
        self.cls == other.cls
            && match (&self.union_membership, &other.union_membership) {
                (Some(a), Some(b)) => a.get() == b.get(),
                (None, None) => true,
                _ => false,
            }
    }
}

impl Eq for CacheKey {}

impl Hash for CacheKey {
    fn hash<H: Hasher>(&self, state: &mut H) {
        self.cls.hash(state);
        match &self.union_membership {
            Some(um) => um.get().hash(state),
            None => 0_u8.hash(state),
        }
    }
}

static CLASS_FIELD_TYPES_CACHE: OnceLock<Mutex<FnvHashMap<CacheKey, Py<PyAny>>>> = OnceLock::new();
static PLUGIN_FIELDS_CACHE: OnceLock<Mutex<FnvHashMap<CacheKey, Py<PyTuple>>>> = OnceLock::new();
static FIELD_ALIASES_CACHE: OnceLock<Mutex<FnvHashMap<CacheKey, Py<PyDict>>>> = OnceLock::new();

fn warn_or_error<'py>(py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
    import_attr(py, &WARN_OR_ERROR, "pants.base.deprecated", "warn_or_error")
}

fn invalid_target_exception<'py>(py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
    import_target_attr(py, &INVALID_TARGET_EXCEPTION, "InvalidTargetException")
}

fn target_generator_cls<'py>(py: Python<'py>) -> PyResult<Bound<'py, PyType>> {
    import_type(
        py,
        &TARGET_GENERATOR_CLS,
        "pants.engine.target",
        "TargetGenerator",
    )
}

fn cache_key(
    cls: &Bound<'_, PyType>,
    union_membership: Option<&Bound<'_, PyAny>>,
) -> PyResult<CacheKey> {
    let union_membership = match union_membership {
        None => None,
        Some(um) => Some(um.extract::<Py<UnionMembership>>()?),
    };
    Ok(CacheKey {
        cls: TypeId::new(cls),
        union_membership,
    })
}

fn cached<'py, T>(
    cache: &OnceLock<Mutex<FnvHashMap<CacheKey, Py<T>>>>,
    key: CacheKey,
    py: Python<'py>,
    compute: impl FnOnce() -> PyResult<Bound<'py, T>>,
) -> PyResult<Bound<'py, T>> {
    let cache = cache.get_or_init(|| Mutex::new(FnvHashMap::default()));
    {
        let locked = cache.lock();
        if let Some(cached) = locked.get(&key) {
            return Ok(cached.bind(py).clone());
        }
    }
    let value = compute()?;
    let mut locked = cache.lock();
    Ok(locked
        .entry(key)
        .or_insert_with(|| value.unbind())
        .bind(py)
        .clone())
}

/// A Target represents an addressable set of metadata.
///
///     Set the `help` class property with a description, which will be used in `./pants help`. For the
///     best rendering, use soft wrapping (e.g. implicit string concatenation) within paragraphs, but
///     hard wrapping (`
/// `) to separate distinct paragraphs and/or lists.
// Reproduces the original Python docstring exactly (incl. indentation/trailing whitespace), as
// asserted by help_info_extracter_test; pyo3 strips one leading space here as it does for `///`.
#[doc = "     "]
#[pyclass(subclass, frozen, module = "pants.engine.target")]
pub struct Target {
    address: Py<Address>,
    field_values: Py<FrozenDict>,
    residence_dir: PyBackedStr,
    name_explicitly_set: bool,
    description_of_origin: PyBackedStr,
    origin_sources_blocks: Py<FrozenDict>,
}

#[pymethods]
impl Target {
    #[classattr]
    fn removal_version(py: Python) -> Py<PyAny> {
        py.None()
    }

    #[classattr]
    fn removal_hint(py: Python) -> Py<PyAny> {
        py.None()
    }

    #[classattr]
    fn deprecated_alias(py: Python) -> Py<PyAny> {
        py.None()
    }

    #[classattr]
    fn deprecated_alias_removal_version(py: Python) -> Py<PyAny> {
        py.None()
    }

    #[new]
    #[classmethod]
    #[pyo3(signature = (
        unhydrated_values,
        address,
        union_membership=None,
        *,
        name_explicitly_set=true,
        residence_dir=None,
        ignore_unrecognized_fields=false,
        description_of_origin=None,
        origin_sources_blocks=None,
    ))]
    fn __new__(
        cls: &Bound<'_, PyType>,
        unhydrated_values: &Bound<'_, PyAny>,
        address: Bound<'_, Address>,
        union_membership: Option<Bound<'_, PyAny>>,
        name_explicitly_set: bool,
        residence_dir: Option<PyBackedStr>,
        ignore_unrecognized_fields: bool,
        description_of_origin: Option<PyBackedStr>,
        origin_sources_blocks: Option<Bound<'_, PyAny>>,
        py: Python,
    ) -> PyResult<Self> {
        Self::check_removal_version(cls, &address, py)?;

        let origin_sources_blocks = match origin_sources_blocks {
            None => FrozenDict::empty(py).unbind(),
            Some(obj) => {
                let Ok(blocks) = obj.cast::<FrozenDict>() else {
                    return Err(PyValueError::new_err(format!(
                        "Expected `origin_sources_blocks` to be of type `FrozenDict`, got {} {}",
                        obj.get_type(),
                        obj.repr()?
                    )));
                };
                if blocks.as_any().is_truthy()? {
                    Self::validate_origin_sources_blocks(blocks, py)?;
                }
                blocks.clone().unbind()
            }
        };

        let field_values: Py<FrozenDict> = match Self::calculate_field_values(
            cls,
            unhydrated_values,
            &address,
            union_membership.as_ref().map(|um| um.as_any()),
            ignore_unrecognized_fields,
            py,
        ) {
            Ok(fv) => fv.extract()?,
            Err(error) => {
                let origin = description_of_origin
                    .as_deref()
                    .filter(|s| !s.is_empty())
                    .or(residence_dir.as_deref())
                    .unwrap_or(address.get().spec_path_str());
                let exc_cls = invalid_target_exception(py)?;
                let kwargs = PyDict::new(py);
                kwargs.set_item(intern!(py, "description_of_origin"), origin)?;
                let err =
                    PyErr::from_value(exc_cls.call((error.value(py).str()?,), Some(&kwargs))?);
                err.set_cause(py, Some(error));
                return Err(err);
            }
        };

        let residence_dir_val = match residence_dir {
            Some(rd) => rd,
            None => pyo3::types::PyString::new(py, address.get().spec_path_str()).extract()?,
        };
        let description_of_origin_val = match description_of_origin {
            Some(doo) if !doo.is_empty() => doo,
            _ => residence_dir_val.clone_ref(py),
        };

        Ok(Self {
            address: address.unbind(),
            field_values,
            residence_dir: residence_dir_val,
            name_explicitly_set,
            description_of_origin: description_of_origin_val,
            origin_sources_blocks,
        })
    }

    #[pyo3(signature = (*_args, **_kwargs))]
    fn __init__(
        self_: &Bound<'_, Self>,
        _args: &Bound<'_, PyTuple>,
        _kwargs: Option<&Bound<'_, PyDict>>,
        py: Python,
    ) -> PyResult<()> {
        match self_.call_method0(intern!(py, "validate")) {
            Ok(_) => Ok(()),
            Err(error) => {
                let inner = self_.get();
                let description: &str = &inner.description_of_origin;
                let exc_cls = invalid_target_exception(py)?;
                let kwargs = PyDict::new(py);
                kwargs.set_item(intern!(py, "description_of_origin"), description)?;
                let err =
                    PyErr::from_value(exc_cls.call((error.value(py).str()?,), Some(&kwargs))?);
                err.set_cause(py, Some(error));
                Err(err)
            }
        }
    }

    #[getter]
    fn address(&self) -> &Py<Address> {
        &self.address
    }

    #[getter]
    fn field_values(&self) -> &Py<FrozenDict> {
        &self.field_values
    }

    #[getter]
    fn residence_dir(&self) -> &PyBackedStr {
        &self.residence_dir
    }

    #[getter]
    fn name_explicitly_set(&self) -> bool {
        self.name_explicitly_set
    }

    #[getter]
    fn description_of_origin(&self) -> &PyBackedStr {
        &self.description_of_origin
    }

    #[getter]
    fn origin_sources_blocks(&self) -> &Py<FrozenDict> {
        &self.origin_sources_blocks
    }

    #[getter]
    fn field_types<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        FrozenDict::py_keys(self.field_values.bind(py))
    }

    fn __hash__(self_: &Bound<'_, Self>, py: Python) -> PyResult<isize> {
        let inner = self_.get();
        let mut residence_hasher = FnvHasher::default();
        (*inner.residence_dir).hash(&mut residence_hasher);
        Ok(combine_hashes(&[
            self_.get_type().hash()?,
            inner.address.bind(py).as_any().hash()?,
            residence_hasher.finish() as isize,
            inner.field_values.get().cached_hash(),
        ]))
    }

    fn __richcmp__(
        self_: &Bound<'_, Self>,
        other: &Bound<'_, PyAny>,
        op: CompareOp,
        py: Python,
    ) -> PyResult<PyComparedBool> {
        if !other.is_instance_of::<Target>() {
            return Ok(PyComparedBool(None)); // NotImplemented
        }
        let other_target = other.extract::<PyRef<Target>>()?;
        match op {
            CompareOp::Eq | CompareOp::Ne => {
                let inner = self_.get();
                let is_eq = self_.get_type().is(other.get_type())
                    && *inner.residence_dir == *other_target.residence_dir
                    && inner
                        .address
                        .bind(py)
                        .as_any()
                        .eq(other_target.address.bind(py).as_any())?
                    && inner
                        .field_values
                        .get()
                        .eq(other_target.field_values.get(), py)?;
                Ok(PyComparedBool::eq_ne(op, is_eq))
            }
            CompareOp::Lt => Ok(PyComparedBool(Some(
                self_
                    .get()
                    .address
                    .bind(py)
                    .as_any()
                    .lt(other_target.address.bind(py).as_any())?,
            ))),
            CompareOp::Gt => Ok(PyComparedBool(Some(
                self_
                    .get()
                    .address
                    .bind(py)
                    .as_any()
                    .gt(other_target.address.bind(py).as_any())?,
            ))),
            _ => Ok(PyComparedBool(None)),
        }
    }

    fn __repr__(self_: &Bound<'_, Self>, py: Python) -> PyResult<String> {
        let inner = self_.get();
        let cls = self_.get_type();
        let alias: PyBackedStr = cls.getattr(intern!(py, "alias"))?.extract()?;
        let fields = format_field_values(&inner.field_values, py)?;
        Ok(format!(
            "{cls}(address={}, alias={:?}, residence_dir={:?}, origin={}, {fields})",
            inner.address.bind(py),
            &*alias,
            &*inner.residence_dir,
            &*inner.description_of_origin,
        ))
    }

    fn __str__(self_: &Bound<'_, Self>, py: Python) -> PyResult<String> {
        let inner = self_.get();
        let alias: PyBackedStr = self_.get_type().getattr(intern!(py, "alias"))?.extract()?;
        let fields = format_field_values(&inner.field_values, py)?;
        let address = inner.address.bind(py);
        let sep = if fields.is_empty() { "" } else { ", " };
        Ok(format!("{alias}(address=\"{address}\"{sep}{fields})"))
    }

    fn __getitem__<'py>(
        self_: &Bound<'py, Self>,
        field: &Bound<'py, PyType>,
        py: Python<'py>,
    ) -> PyResult<Bound<'py, PyAny>> {
        if let Some(result) = Self::maybe_get_impl(self_, field, py)? {
            return Ok(result);
        }
        let field_name: PyBackedStr = field.getattr(intern!(py, "__name__"))?.extract()?;
        Err(PyKeyError::new_err(format!(
            "The target `{self_}` does not have a field `{field_name}`. Before calling \
             `my_tgt[{field_name}]`, call `my_tgt.has_field({field_name})` to \
             filter out any irrelevant Targets or call `my_tgt.get({field_name})` to use the \
             default Field value."
        )))
    }

    #[pyo3(signature = (field, *, default_raw_value=None))]
    fn get<'py>(
        self_: &Bound<'py, Self>,
        field: &Bound<'py, PyType>,
        default_raw_value: Option<Bound<'py, PyAny>>,
        py: Python<'py>,
    ) -> PyResult<Bound<'py, PyAny>> {
        if let Some(result) = Self::maybe_get_impl(self_, field, py)? {
            return Ok(result);
        }
        let address = self_.get().address.bind(py);
        field.call1((default_raw_value, address))
    }

    fn _maybe_get<'py>(
        self_: &Bound<'py, Self>,
        field: &Bound<'py, PyType>,
        py: Python<'py>,
    ) -> PyResult<Option<Bound<'py, PyAny>>> {
        Self::maybe_get_impl(self_, field, py)
    }

    fn has_field(self_: &Bound<'_, Self>, field: &Bound<'_, PyType>, py: Python) -> PyResult<bool> {
        let field_values = self_.get().field_values.get();
        if field_values.contains(field.as_any())? {
            return Ok(true);
        }
        let keys = FrozenDict::py_keys(self_.get().field_values.bind(py))?;
        Ok(Self::find_registered_field_subclass_impl(field, &keys, py)?.is_some())
    }

    fn has_fields(
        self_: &Bound<'_, Self>,
        fields: &Bound<'_, PyAny>,
        py: Python,
    ) -> PyResult<bool> {
        let keys = self_
            .get()
            .field_values
            .bind(py)
            .call_method0(intern!(py, "keys"))?;
        Self::check_has_fields(fields, &keys, py)
    }

    #[classmethod]
    fn _has_fields(
        _cls: &Bound<'_, PyType>,
        fields: &Bound<'_, PyAny>,
        registered_fields: &Bound<'_, PyAny>,
        py: Python,
    ) -> PyResult<bool> {
        Self::check_has_fields(fields, registered_fields, py)
    }

    #[classmethod]
    fn _find_registered_field_subclass<'py>(
        _cls: &Bound<'py, PyType>,
        requested_field: &Bound<'py, PyType>,
        registered_fields: &Bound<'py, PyAny>,
        py: Python<'py>,
    ) -> PyResult<Option<Bound<'py, PyAny>>> {
        Self::find_registered_field_subclass_impl(requested_field, registered_fields, py)
    }

    #[classmethod]
    fn class_field_types<'py>(
        cls: &Bound<'py, PyType>,
        union_membership: Option<&Bound<'py, PyAny>>,
        py: Python<'py>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let key = cache_key(cls, union_membership)?;
        cached(&CLASS_FIELD_TYPES_CACHE, key, py, || {
            let core_fields = cls.getattr(intern!(py, "core_fields"))?;
            let fos = match union_membership {
                None => FrozenOrderedSet::from_iterable(Some(&core_fields))?,
                Some(um) => {
                    let plugin_fields =
                        cls.call_method1(intern!(py, "_find_plugin_fields"), (um,))?;
                    let combined = PyTuple::new(
                        py,
                        core_fields
                            .try_iter()?
                            .chain(plugin_fields.try_iter()?)
                            .collect::<PyResult<Vec<_>>>()?,
                    )?;
                    FrozenOrderedSet::from_iterable(Some(combined.as_any()))?
                }
            };
            Ok(Bound::new(py, fos)?.into_any())
        })
    }

    #[classmethod]
    fn class_has_field(
        cls: &Bound<'_, PyType>,
        field: &Bound<'_, PyType>,
        union_membership: &Bound<'_, PyAny>,
        py: Python,
    ) -> PyResult<bool> {
        let fields = PyList::new(py, [field])?;
        Self::class_has_fields(cls, &fields.into_any(), union_membership, py)
    }

    #[classmethod]
    fn class_has_fields(
        cls: &Bound<'_, PyType>,
        fields: &Bound<'_, PyAny>,
        union_membership: &Bound<'_, PyAny>,
        py: Python,
    ) -> PyResult<bool> {
        let registered = Self::class_field_types(cls, Some(union_membership), py)?;
        Self::_has_fields(cls, fields, &registered, py)
    }

    #[classmethod]
    fn class_get_field<'py>(
        cls: &Bound<'py, PyType>,
        field: &Bound<'py, PyType>,
        union_membership: &Bound<'py, PyAny>,
        py: Python<'py>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let class_fields = Self::class_field_types(cls, Some(union_membership), py)?;
        let result = Self::find_registered_field_subclass_impl(field, &class_fields, py)?;
        match result {
            Some(found) => Ok(found),
            None => {
                let alias: PyBackedStr = cls.getattr(intern!(py, "alias"))?.extract()?;
                let field_name: PyBackedStr = field.getattr(intern!(py, "__name__"))?.extract()?;
                Err(PyKeyError::new_err(format!(
                    "The target type `{alias}` does not have a field `{field_name}`. Before \
                     calling `TargetType.class_get_field({field_name})`, call \
                     `TargetType.class_has_field({field_name})`."
                )))
            }
        }
    }

    #[classmethod]
    fn _find_plugin_fields<'py>(
        cls: &Bound<'py, PyType>,
        union_membership: &Bound<'py, PyAny>,
        py: Python<'py>,
    ) -> PyResult<Bound<'py, PyTuple>> {
        let key = cache_key(cls, Some(union_membership))?;
        cached(&PLUGIN_FIELDS_CACHE, key, py, || {
            let target_type = py.get_type::<Target>();
            let result = PySet::empty(py)?;
            let mut classes: Vec<Bound<'_, PyType>> = vec![cls.clone()];

            while let Some(current) = classes.pop() {
                let bases = current.getattr(intern!(py, "__bases__"))?;
                for base in bases.try_iter()? {
                    let base: Bound<'_, PyType> = base?.extract()?;
                    classes.push(base);
                }
                if current.is_subclass(&target_type)?
                    && let Ok(plugin_field) = current.getattr(intern!(py, "PluginField"))
                    && let Ok(plugin_field_type) = plugin_field.extract::<Bound<'_, PyType>>()
                {
                    let members =
                        union_membership.call_method1(intern!(py, "get"), (&plugin_field_type,))?;
                    for member in members.try_iter()? {
                        result.add(member?)?;
                    }
                }
            }

            let mut with_aliases: Vec<(PyBackedStr, Bound<'_, PyAny>)> = result
                .iter()
                .map(|item| Ok((extract_alias(&item)?, item)))
                .collect::<PyResult<_>>()?;
            sort_by_alias(&mut with_aliases);
            PyTuple::new(py, with_aliases.iter().map(|(_, item)| item))
        })
    }

    #[classmethod]
    fn register_plugin_field<'py>(
        cls: &Bound<'py, PyType>,
        field: &Bound<'py, PyType>,
        py: Python<'py>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let plugin_field = cls.getattr(intern!(py, "PluginField"))?;
        let union_rule_cls = py.get_type::<UnionRule>();
        union_rule_cls.call1((&plugin_field, field))
    }

    fn validate(&self) -> PyResult<()> {
        Ok(())
    }

    #[classmethod]
    fn _get_field_aliases_to_field_types<'py>(
        _cls: &Bound<'py, PyType>,
        field_types: &Bound<'py, PyAny>,
        py: Python<'py>,
    ) -> PyResult<Bound<'py, PyDict>> {
        Self::get_field_aliases_to_field_types(field_types, py)
    }

    #[classattr]
    #[pyo3(name = "PluginField")]
    fn plugin_field(py: Python) -> PyResult<PluginFieldDescriptor> {
        let bases = PyTuple::new(py, Vec::<Bound<'_, PyAny>>::new())?;
        let dict = PyDict::new(py);
        dict.set_item("__qualname__", "Target.PluginField")?;
        let type_metaclass = py.get_type::<PyType>();
        let base_class: Bound<'_, PyType> = type_metaclass
            .call1(("PluginField", bases, dict))?
            .extract()?;
        Ok(PluginFieldDescriptor::new(base_class.unbind()))
    }
}

fn sort_by_alias<T>(items: &mut [(PyBackedStr, T)]) {
    items.sort_by(|(a, _), (b, _)| a.cmp(b));
}

fn extract_alias<'py>(field_type: &Bound<'py, PyAny>) -> PyResult<PyBackedStr> {
    field_type
        .getattr(intern!(field_type.py(), "alias"))?
        .extract()
}

fn format_field_values(field_values: &Py<FrozenDict>, py: Python) -> PyResult<String> {
    let values = field_values.bind(py).call_method0(intern!(py, "values"))?;
    let mut result = String::new();
    for (i, field) in values.try_iter()?.enumerate() {
        if i > 0 {
            result.push_str(", ");
        }
        write!(result, "{}", field?.str()?).unwrap();
    }
    Ok(result)
}

impl Target {
    fn calculate_field_values<'py>(
        cls: &Bound<'py, PyType>,
        unhydrated_values: &Bound<'py, PyAny>,
        address: &Bound<'py, Address>,
        union_membership: Option<&Bound<'py, PyAny>>,
        ignore_unrecognized_fields: bool,
        py: Python<'py>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let all_field_types = Self::class_field_types(cls, union_membership, py)?;
        let aliases_to_field_types =
            Self::cached_field_aliases(cls, union_membership, &all_field_types, py)?;
        let field_values = PyDict::new(py);

        Self::hydrate_fields(
            cls,
            &aliases_to_field_types,
            unhydrated_values,
            address,
            &field_values,
            ignore_unrecognized_fields,
            py,
        )?;
        Self::fill_defaults(&all_field_types, &field_values, address)?;
        Self::to_sorted_frozen_dict(&field_values, py)
    }

    fn hydrate_fields<'py>(
        cls: &Bound<'py, PyType>,
        aliases_to_field_types: &Bound<'py, PyDict>,
        unhydrated_values: &Bound<'py, PyAny>,
        address: &Bound<'py, Address>,
        field_values: &Bound<'py, PyDict>,
        ignore_unrecognized_fields: bool,
        py: Python<'py>,
    ) -> PyResult<()> {
        for item in unhydrated_values
            .call_method0(intern!(py, "items"))?
            .try_iter()?
        {
            let item = item?;
            let (alias, value) = item.extract::<(Bound<'_, PyAny>, Bound<'_, PyAny>)>()?;

            match aliases_to_field_types.get_item(&alias)? {
                Some(field_type) => {
                    field_values.set_item(&field_type, field_type.call1((&value, address))?)?;
                }
                None if ignore_unrecognized_fields => {}
                None => {
                    return Self::raise_unrecognized_field(
                        cls,
                        &alias,
                        &value,
                        address,
                        aliases_to_field_types,
                        py,
                    );
                }
            }
        }
        Ok(())
    }

    fn fill_defaults<'py>(
        all_field_types: &Bound<'py, PyAny>,
        field_values: &Bound<'py, PyDict>,
        address: &Bound<'py, Address>,
    ) -> PyResult<()> {
        let no_value = NoFieldValue::expect_singleton();
        for field_type in all_field_types.try_iter()? {
            let field_type = field_type?;
            if !field_values.contains(&field_type)? {
                field_values.set_item(&field_type, field_type.call1((&no_value, address))?)?;
            }
        }
        Ok(())
    }

    fn raise_unrecognized_field(
        cls: &Bound<'_, PyType>,
        alias: &Bound<'_, PyAny>,
        value: &Bound<'_, PyAny>,
        address: &Bound<'_, Address>,
        aliases_to_field_types: &Bound<'_, PyDict>,
        py: Python,
    ) -> PyResult<()> {
        let valid_aliases = PySet::empty(py)?;
        for (key, _) in aliases_to_field_types.iter() {
            valid_aliases.add(key)?;
        }
        if let Ok(tg_cls) = target_generator_cls(py)
            && cls.is_subclass(&tg_cls)?
        {
            for ft in cls.getattr(intern!(py, "moved_fields"))?.try_iter()? {
                let ft = ft?;
                valid_aliases.add(ft.getattr(intern!(py, "alias"))?)?;
                if let Ok(dep_alias) = ft.getattr(intern!(py, "deprecated_alias"))
                    && !dep_alias.is_none()
                {
                    valid_aliases.add(dep_alias)?;
                }
            }
        }
        let alias_str: PyBackedStr = cls.getattr(intern!(py, "alias"))?.extract()?;
        let mut sorted: Vec<String> = valid_aliases
            .iter()
            .map(|a| a.extract::<String>())
            .collect::<PyResult<_>>()?;
        sorted.sort();
        let msg = format!(
            "Unrecognized field `{alias}={value}` in target {address}. Valid fields for \
             the target type `{alias_str}`: {}.",
            PyReprList(&sorted),
        );
        Err(raise_invalid_field(py, msg))
    }

    fn to_sorted_frozen_dict<'py>(
        field_values: &Bound<'py, PyDict>,
        py: Python<'py>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let mut items: Vec<(PyBackedStr, Bound<'_, PyAny>, Bound<'_, PyAny>)> = field_values
            .iter()
            .map(|(k, v)| Ok((extract_alias(&k)?, k, v)))
            .collect::<PyResult<_>>()?;
        items.sort_by(|(a, _, _), (b, _, _)| a.cmp(b));
        let sorted_dict = PyDict::new(py);
        for (_, key, value) in &items {
            sorted_dict.set_item(key, value)?;
        }
        FrozenDict::from_pydict(sorted_dict)?.into_bound_py_any(py)
    }

    fn validate_origin_sources_blocks(blocks: &Bound<'_, FrozenDict>, py: Python) -> PyResult<()> {
        let source_blocks_type = py.get_type::<super::adaptor::SourceBlocks>();
        let source_block_type = py.get_type::<super::adaptor::SourceBlock>();
        for value in blocks
            .as_any()
            .call_method0(intern!(py, "values"))?
            .try_iter()?
        {
            let value = value?;
            if !value.is_instance(&source_blocks_type)? {
                return Err(PyValueError::new_err(format!(
                    "Expected `origin_sources_blocks` values to be `SourceBlocks`, got {value}"
                )));
            }
            for block in value.try_iter()? {
                let block = block?;
                if !block.is_instance(source_block_type.as_any())? {
                    return Err(PyValueError::new_err(format!(
                        "Expected `origin_sources_blocks` elements to be `SourceBlock`, got {block}"
                    )));
                }
            }
        }
        Ok(())
    }

    fn check_removal_version(
        cls: &Bound<'_, PyType>,
        address: &Bound<'_, Address>,
        py: Python,
    ) -> PyResult<()> {
        if address.get().is_generated_target() {
            return Ok(());
        }
        let removal_version = cls.getattr(intern!(py, "removal_version"))?;
        if !removal_version.is_truthy()? {
            return Ok(());
        }
        let removal_hint = cls.getattr(intern!(py, "removal_hint"))?;
        if removal_hint.is_none() {
            return Err(PyValueError::new_err(format!(
                "You specified `removal_version` for {cls}, but not the class property `removal_hint`."
            )));
        }
        let alias: PyBackedStr = cls.getattr(intern!(py, "alias"))?.extract()?;
        warn_or_error(py)?.call(
            (
                &removal_version,
                format!("the {:?} target type", &*alias),
                format!(
                    "Using the `{alias}` target type for {address}. {}",
                    removal_hint.str()?
                ),
            ),
            None,
        )?;
        Ok(())
    }

    fn maybe_get_impl<'py>(
        self_: &Bound<'py, Self>,
        field: &Bound<'py, PyType>,
        py: Python<'py>,
    ) -> PyResult<Option<Bound<'py, PyAny>>> {
        let field_values = self_.get().field_values.bind(py);

        if let Some(result) = field_values.get().get_opt(field.as_any())? {
            return Ok(Some(result));
        }

        let keys = FrozenDict::py_keys(field_values)?;
        if let Some(subclass) = Self::find_registered_field_subclass_impl(field, &keys, py)? {
            return field_values.get().get_opt(&subclass);
        }

        Ok(None)
    }

    fn find_registered_field_subclass_impl<'py>(
        requested_field: &Bound<'py, PyType>,
        registered_fields: &Bound<'py, PyAny>,
        _py: Python<'py>,
    ) -> PyResult<Option<Bound<'py, PyAny>>> {
        for registered in registered_fields.try_iter()? {
            let registered = registered?;
            let registered_type: &Bound<'_, PyType> = registered.cast()?;
            if registered_type.is_subclass(requested_field)? {
                return Ok(Some(registered));
            }
        }
        Ok(None)
    }

    fn check_has_fields(
        fields: &Bound<'_, PyAny>,
        registered_fields: &Bound<'_, PyAny>,
        py: Python,
    ) -> PyResult<bool> {
        for field in fields.try_iter()? {
            let field = field?;
            if registered_fields.contains(&field)? {
                continue;
            }
            let subclass = Self::find_registered_field_subclass_impl(
                &field.extract()?,
                registered_fields,
                py,
            )?;
            if subclass.is_none() {
                return Ok(false);
            }
        }
        Ok(true)
    }

    fn cached_field_aliases<'py>(
        cls: &Bound<'py, PyType>,
        union_membership: Option<&Bound<'py, PyAny>>,
        all_field_types: &Bound<'py, PyAny>,
        py: Python<'py>,
    ) -> PyResult<Bound<'py, PyDict>> {
        let key = cache_key(cls, union_membership)?;
        cached(&FIELD_ALIASES_CACHE, key, py, || {
            Self::get_field_aliases_to_field_types(all_field_types, py)
        })
    }

    fn get_field_aliases_to_field_types<'py>(
        field_types: &Bound<'py, PyAny>,
        py: Python<'py>,
    ) -> PyResult<Bound<'py, PyDict>> {
        let result = PyDict::new(py);
        for field_type in field_types.try_iter()? {
            let field_type = field_type?;
            let alias = field_type.getattr(intern!(py, "alias"))?;
            result.set_item(&alias, &field_type)?;
            if let Ok(deprecated_alias) = field_type.getattr(intern!(py, "deprecated_alias"))
                && !deprecated_alias.is_none()
            {
                result.set_item(&deprecated_alias, &field_type)?;
            }
        }
        Ok(result)
    }
}

pub fn register(module: &Bound<'_, pyo3::types::PyModule>) -> PyResult<()> {
    module.add_class::<Target>()?;
    Ok(())
}
