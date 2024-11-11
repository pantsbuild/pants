// Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use pyo3::prelude::*;
use pyo3::types::{PyBool, PyDict, PyFloat, PyInt, PyList, PyString, PyTuple};

use options::{
    apply_dict_edits, apply_list_edits, Args, ConfigSource, DictEdit, DictEditAction, Env,
    ListEdit, ListEditAction, ListOptionValue, OptionId, OptionParser, OptionalOptionValue, Scope,
    Source, Val,
};

use std::collections::HashMap;

pyo3::import_exception!(pants.option.errors, ParseError);

pub(crate) fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyOptionId>()?;
    m.add_class::<PyConfigSource>()?;
    m.add_class::<PyOptionParser>()?;
    Ok(())
}

// The (nested) values of a dict-valued option are represented by Val.
// This function converts them to equivalent Python types.
fn val_to_py_object(py: Python, val: &Val) -> PyResult<PyObject> {
    let res = match val {
        Val::Bool(b) => b.into_py(py),
        Val::Int(i) => i.into_py(py),
        Val::Float(f) => f.into_py(py),
        Val::String(s) => s.into_py(py),
        Val::List(list) => {
            let pylist = PyList::empty_bound(py);
            for m in list {
                pylist.append(val_to_py_object(py, m)?)?;
            }
            pylist.into_py(py)
        }
        Val::Dict(dict) => {
            let pydict = PyDict::new_bound(py);
            for (k, v) in dict {
                pydict.set_item(k.into_py(py), val_to_py_object(py, v)?)?;
            }
            pydict.into_py(py)
        }
    };
    Ok(res)
}

// Converts a string->Val dict into a Python type.
fn dict_into_py(py: Python, vals: HashMap<String, Val>) -> PyResult<PyDictVal> {
    vals.into_iter()
        .map(|(k, v)| match val_to_py_object(py, &v) {
            Ok(pyobj) => Ok((k, pyobj)),
            Err(err) => Err(err),
        })
        .collect::<PyResult<HashMap<String, PyObject>>>()
}

// Converts a Python object into a Val, which is necessary for receiving
// the default values of dict-valued options from Python.
pub(crate) fn py_object_to_val(obj: &Bound<'_, PyAny>) -> Result<Val, PyErr> {
    // TODO: If this is_instance_of chain shows up as significant in CPU profiles,
    //  we can use a lookup table of PyTypeObject -> conversion func instead.
    //  Alternatively, we could type-parameterize DictEdit to create a variant that contains
    //  Py* types directly,instead of Vals, for when dict-valued options are consumed by
    //  Python code, while retaining the current Val-based DictEdit for when dict-valued
    //  options are consumed in Rust code.
    //  However we don't have many dict-typed options, and even fewer with non-empty or non-tiny
    //  defaults (this function is only used to convert option default values), so it's
    //  very unlikely that this is a problem in practice.

    // NB: We check these in rough order of likelihood of the type appearing in a dict value,
    // but it is vital that we check bool before int, because bool is a subclass of int.
    if obj.is_instance_of::<PyString>() {
        Ok(Val::String(obj.extract()?))
    } else if obj.is_instance_of::<PyBool>() {
        Ok(Val::Bool(obj.extract()?))
    } else if obj.is_instance_of::<PyInt>() {
        Ok(Val::Int(obj.extract()?))
    } else if obj.is_instance_of::<PyFloat>() {
        Ok(Val::Float(obj.extract()?))
    } else if obj.is_instance_of::<PyDict>() {
        Ok(Val::Dict(
            obj.downcast::<PyDict>()?
                .iter()
                .map(|(k, v)| {
                    Ok::<(String, Val), PyErr>((k.extract::<String>()?, py_object_to_val(&v)?))
                })
                .collect::<Result<HashMap<_, _>, _>>()?,
        ))
    } else if obj.is_instance_of::<PyList>() {
        Ok(Val::List(
            obj.downcast::<PyList>()?
                .iter()
                .map(|v| py_object_to_val(&v))
                .collect::<Result<Vec<_>, _>>()?,
        ))
    } else if obj.is_instance_of::<PyTuple>() {
        Ok(Val::List(
            obj.downcast::<PyTuple>()?
                .iter()
                .map(|v| py_object_to_val(&v))
                .collect::<Result<Vec<_>, _>>()?,
        ))
    } else {
        Err(ParseError::new_err(format!(
            "Unsupported Python type in option default: {}",
            obj.get_type().name()?
        )))
    }
}

#[pyclass]
struct PyOptionId(OptionId);

#[pymethods]
impl PyOptionId {
    #[new]
    #[pyo3(signature = (*components, scope = None, switch = None))]
    fn __new__(
        components: &Bound<'_, PyTuple>,
        scope: Option<&str>,
        switch: Option<&str>,
    ) -> PyResult<Self> {
        let components = components
            .iter()
            .map(|c| c.extract::<String>())
            .collect::<Result<Vec<_>, _>>()?;
        let scope = scope.map(Scope::named).unwrap_or(Scope::Global);
        let switch = match switch {
            Some(switch) if switch.len() == 1 => switch.chars().next(),
            None => None,
            Some(s) => {
                return Err(ParseError::new_err(format!(
                    "Switch value should contain a single character, but was: {}",
                    s
                )))
            }
        };
        let option_id =
            OptionId::new(scope, components.into_iter(), switch).map_err(ParseError::new_err)?;
        Ok(Self(option_id))
    }
}

#[pyclass]
struct PyConfigSource(ConfigSource);

#[pymethods]
impl PyConfigSource {
    #[new]
    fn __new__(path: &str, content: &[u8]) -> PyResult<Self> {
        Ok(Self(ConfigSource {
            path: path.into(),
            content: std::str::from_utf8(content).map(str::to_string)?,
        }))
    }
}

#[pyclass]
struct PyOptionParser(OptionParser);

// The pythonic value of a dict-typed option.
type PyDictVal = HashMap<String, PyObject>;

// The derivation of the option value, as a vec of (value, vec of source ranks) tuples.
// A scalar value will always have a single source. A list/dict value may have elements
// appended across multiple sources.
// In ascending rank order, so the last value is the final value of the option.
type OptionValueDerivation<T> = Vec<(T, Vec<isize>)>;

// A tuple (final value, rank of final value, optional derivation of value).
//
// Note: The final value and its rank could be computed from the derivation (see above),
// but the full derivation is not itself computed in normal usage.
// We could get rid of this tuple type by representing the final value and its rank as
// a singleton derivation (in the case where we don't otherwise need the full derivation).
// But that would allocate two unnecessary Vecs for every option.
type OptionValue<T> = (Option<T>, isize, Option<OptionValueDerivation<T>>);

// Condense list value derivation across sources, so that it reflects merges vs. replacements
// in a useful way. E.g., if we merge [a, b] and [c], and then replace it with [d, e],
// the derivation will show:
//   - [d, e] (from command-line flag)
//   - [a, b, c] (from env var, from config)
fn condense_list_value_derivation<T: PartialEq>(
    derivation: Vec<(Source, Vec<ListEdit<T>>)>,
) -> OptionValueDerivation<Vec<T>> {
    let mut ret: OptionValueDerivation<Vec<T>> = vec![];
    let mut cur_group = vec![];
    let mut cur_ranks = vec![];

    // In this case, for simplicity, we always use the "inefficient" O(M*N) remover,
    // even for hashable values. This is very unlikely to have a noticeable performance impact
    // in practice. And if it does, it would only be when we generate option value derivation
    // for help display, and not in regular usage.
    // See comments on OptionParser::parse_list_hashable() for context.
    fn remover<T: PartialEq>(list: &mut Vec<T>, to_remove: &[T]) {
        list.retain(|item| !to_remove.contains(item));
    }

    for (source, list_edits) in derivation.into_iter() {
        for list_edit in list_edits {
            if list_edit.action == ListEditAction::Replace {
                if !cur_group.is_empty() {
                    ret.push((
                        apply_list_edits::<T>(remover, cur_group.into_iter()),
                        cur_ranks,
                    ));
                }
                cur_group = vec![];
                cur_ranks = vec![];
            }
            cur_group.push(list_edit);
            cur_ranks.push(source.rank() as isize);
        }
    }
    if !cur_group.is_empty() {
        ret.push((
            apply_list_edits::<T>(remover, cur_group.into_iter()),
            cur_ranks,
        ));
    }

    ret
}

// Condense dict value derivation across sources, so that it reflects merges vs. replacements
//  in a useful way. E.g., if we merge {a: 1, b: 2] and {c: 3}, and then replace it with {d: 4},
// the derivation will show:
//   - {d: 4} (from command-line flag)
//   - {a: 1, b: 2, c: 3} (from env var, from config)
fn condense_dict_value_derivation(
    py: Python,
    derivation: Vec<(Source, Vec<DictEdit>)>,
) -> PyResult<OptionValueDerivation<PyDictVal>> {
    let mut ret: OptionValueDerivation<PyDictVal> = vec![];
    let mut cur_group = vec![];
    let mut cur_ranks = vec![];

    for (source, dict_edits) in derivation.into_iter() {
        for dict_edit in dict_edits {
            if dict_edit.action == DictEditAction::Replace {
                if !cur_group.is_empty() {
                    ret.push((
                        dict_into_py(py, apply_dict_edits(cur_group.into_iter()))?,
                        cur_ranks,
                    ));
                }
                cur_group = vec![];
                cur_ranks = vec![];
            }
            cur_group.push(dict_edit);
            cur_ranks.push(source.rank() as isize);
        }
    }
    if !cur_group.is_empty() {
        ret.push((
            dict_into_py(py, apply_dict_edits(cur_group.into_iter()))?,
            cur_ranks,
        ));
    }

    Ok(ret)
}

fn into_py<T>(res: Result<OptionalOptionValue<T>, String>) -> PyResult<OptionValue<T>> {
    let val = res.map_err(ParseError::new_err)?;
    Ok((
        val.value,
        val.source.rank() as isize,
        val.derivation.map(|d| {
            d.into_iter()
                .map(|(source, val)| (val, vec![source.rank() as isize]))
                .collect()
        }),
    ))
}

#[allow(clippy::type_complexity)]
impl PyOptionParser {
    fn get_list<T: ToOwned + ?Sized>(
        &self,
        option_id: &Bound<'_, PyOptionId>,
        default: Vec<T::Owned>,
        getter: fn(
            &OptionParser,
            &OptionId,
            Vec<T::Owned>,
        ) -> Result<ListOptionValue<T::Owned>, String>,
    ) -> PyResult<OptionValue<Vec<T::Owned>>>
    where
        <T as ToOwned>::Owned: PartialEq,
    {
        let opt_val =
            getter(&self.0, &option_id.borrow().0, default).map_err(ParseError::new_err)?;
        Ok((
            Some(opt_val.value),
            opt_val.source.rank() as isize,
            opt_val.derivation.map(condense_list_value_derivation),
        ))
    }
}

#[pymethods]
impl PyOptionParser {
    #[new]
    #[pyo3(signature = (args, env, configs, allow_pantsrc, include_derivation))]
    fn __new__<'py>(
        args: Vec<String>,
        env: &Bound<'py, PyDict>,
        configs: Option<Vec<Bound<'py, PyConfigSource>>>,
        allow_pantsrc: bool,
        include_derivation: bool,
    ) -> PyResult<Self> {
        let env = env
            .items()
            .into_iter()
            .map(|kv_pair| kv_pair.extract::<(String, String)>())
            .collect::<Result<HashMap<_, _>, _>>()?;

        let option_parser = OptionParser::new(
            Args::new(args),
            Env::new(env),
            configs.map(|cs| cs.iter().map(|c| c.borrow().0.clone()).collect()),
            allow_pantsrc,
            include_derivation,
            None,
        )
        .map_err(ParseError::new_err)?;
        Ok(Self(option_parser))
    }

    #[pyo3(signature = (option_id, default))]
    fn get_bool(
        &self,
        option_id: &Bound<'_, PyOptionId>,
        default: Option<bool>,
    ) -> PyResult<OptionValue<bool>> {
        into_py(self.0.parse_bool_optional(&option_id.borrow().0, default))
    }

    #[pyo3(signature = (option_id, default))]
    fn get_int(
        &self,
        option_id: &Bound<'_, PyOptionId>,
        default: Option<i64>,
    ) -> PyResult<OptionValue<i64>> {
        into_py(self.0.parse_int_optional(&option_id.borrow().0, default))
    }

    #[pyo3(signature = (option_id, default))]
    fn get_float(
        &self,
        option_id: &Bound<'_, PyOptionId>,
        default: Option<f64>,
    ) -> PyResult<OptionValue<f64>> {
        into_py(self.0.parse_float_optional(&option_id.borrow().0, default))
    }

    #[pyo3(signature = (option_id, default))]
    fn get_string(
        &self,
        option_id: &Bound<'_, PyOptionId>,
        default: Option<&str>,
    ) -> PyResult<OptionValue<String>> {
        into_py(self.0.parse_string_optional(&option_id.borrow().0, default))
    }

    fn get_bool_list(
        &self,
        option_id: &Bound<'_, PyOptionId>,
        default: Vec<bool>,
    ) -> PyResult<OptionValue<Vec<bool>>> {
        self.get_list::<bool>(option_id, default, |op, oid, def| {
            op.parse_bool_list(oid, def)
        })
    }

    fn get_int_list(
        &self,
        option_id: &Bound<'_, PyOptionId>,
        default: Vec<i64>,
    ) -> PyResult<OptionValue<Vec<i64>>> {
        self.get_list::<i64>(option_id, default, |op, oid, def| {
            op.parse_int_list(oid, def)
        })
    }

    fn get_float_list(
        &self,
        option_id: &Bound<'_, PyOptionId>,
        default: Vec<f64>,
    ) -> PyResult<OptionValue<Vec<f64>>> {
        self.get_list::<f64>(option_id, default, |op, oid, def| {
            op.parse_float_list(oid, def)
        })
    }

    fn get_string_list(
        &self,
        option_id: &Bound<'_, PyOptionId>,
        default: Vec<String>,
    ) -> PyResult<OptionValue<Vec<String>>> {
        self.get_list::<String>(option_id, default, |op, oid, def| {
            op.parse_string_list(oid, def)
        })
    }

    fn get_dict(
        &self,
        py: Python,
        option_id: &Bound<'_, PyOptionId>,
        default: &Bound<'_, PyDict>,
    ) -> PyResult<OptionValue<PyDictVal>> {
        let default = default
            .items()
            .into_iter()
            .map(|kv_pair| {
                let (k, v) = kv_pair.extract::<(String, Bound<'_, PyAny>)>()?;
                Ok::<(String, Val), PyErr>((k, py_object_to_val(&v)?))
            })
            .collect::<Result<HashMap<_, _>, _>>()?;

        let opt_val = self
            .0
            .parse_dict(&option_id.borrow().0, default)
            .map_err(ParseError::new_err)?;
        let opt_val_py = dict_into_py(py, opt_val.value)?;

        Ok((
            Some(opt_val_py),
            opt_val.source.rank() as isize,
            match opt_val.derivation {
                Some(d) => Some(condense_dict_value_derivation(py, d)?),
                None => None,
            },
        ))
    }

    fn get_passthrough_args(&self) -> PyResult<Option<Vec<String>>> {
        Ok(self.0.get_passthrough_args().cloned())
    }

    fn get_unconsumed_flags(&self) -> HashMap<String, Vec<String>> {
        // The python side expects an empty string to represent the GLOBAL scope.
        self.0
            .get_unconsumed_flags()
            .into_iter()
            .map(|(k, v)| {
                (
                    (if k.name() == "GLOBAL" { "" } else { k.name() }).to_string(),
                    v,
                )
            })
            .collect()
    }
}
