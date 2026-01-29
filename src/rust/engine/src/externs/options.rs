// Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use pyo3::exceptions::PyException;
use pyo3::types::{PyBool, PyDict, PyFloat, PyInt, PyList, PyString, PyTuple};
use pyo3::{BoundObject, prelude::*};

use options::{
    Args, BuildRoot, ConfigSource, DictEdit, DictEditAction, Env, GoalInfo, ListEdit,
    ListEditAction, ListOptionValue, OptionId, OptionParser, OptionalOptionValue, PantsCommand,
    Scope, Source, Val, apply_dict_edits, apply_list_edits, bin_name,
};

use itertools::Itertools;
use std::collections::{BTreeMap, HashMap, HashSet};
use std::path::PathBuf;

pyo3::import_exception!(pants.option.errors, ParseError);

#[pyfunction]
fn py_bin_name() -> String {
    bin_name()
}

pub(crate) fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(py_bin_name, m)?)?;
    m.add_class::<PyGoalInfo>()?;
    m.add_class::<PyOptionId>()?;
    m.add_class::<PyPantsCommand>()?;
    m.add_class::<PyConfigSource>()?;
    m.add_class::<PyOptionParser>()?;
    Ok(())
}

// The (nested) values of a dict-valued option are represented by Val.
// This function converts them to equivalent Python types.
fn val_to_py_object(py: Python, val: &Val) -> PyResult<Py<PyAny>> {
    let res = match val {
        Val::Bool(b) => b.into_pyobject(py)?.into_any().unbind(),
        Val::Int(i) => i.into_pyobject(py)?.into_any().unbind(),
        Val::Float(f) => f.into_pyobject(py)?.into_any().unbind(),
        Val::String(s) => s.into_pyobject(py)?.into_any().unbind(),
        Val::List(list) => {
            let pylist = PyList::empty(py);
            for m in list {
                pylist.append(val_to_py_object(py, m)?)?;
            }
            pylist.into_pyobject(py)?.into_any().unbind()
        }
        Val::Dict(dict) => {
            let pydict = PyDict::new(py);
            for (k, v) in dict {
                pydict.set_item(k.into_pyobject(py)?, val_to_py_object(py, v)?)?;
            }
            pydict.into_pyobject(py)?.into_any().unbind()
        }
    };
    Ok(res)
}

// Converts a string->Val dict into a Python type.
pub(crate) fn dict_into_py(py: Python, vals: HashMap<String, Val>) -> PyResult<PyDictVal> {
    vals.into_iter()
        .map(|(k, v)| match val_to_py_object(py, &v) {
            Ok(pyobj) => Ok((k, pyobj)),
            Err(err) => Err(err),
        })
        .collect::<PyResult<HashMap<String, Py<PyAny>>>>()
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
            obj.cast::<PyDict>()?
                .iter()
                .map(|(k, v)| {
                    Ok::<(String, Val), PyErr>((k.extract::<String>()?, py_object_to_val(&v)?))
                })
                .collect::<Result<HashMap<_, _>, _>>()?,
        ))
    } else if obj.is_instance_of::<PyList>() {
        Ok(Val::List(
            obj.cast::<PyList>()?
                .iter()
                .map(|v| py_object_to_val(&v))
                .collect::<Result<Vec<_>, _>>()?,
        ))
    } else if obj.is_instance_of::<PyTuple>() {
        Ok(Val::List(
            obj.cast::<PyTuple>()?
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
struct PyGoalInfo(GoalInfo);

#[pymethods]
impl PyGoalInfo {
    #[new]
    fn __new__(
        scope_name: &str,
        is_builtin: bool,
        is_auxiliary: bool,
        aliases: Vec<String>,
    ) -> Self {
        Self(GoalInfo::new(
            scope_name,
            is_builtin,
            is_auxiliary,
            aliases.iter().map(String::as_ref),
        ))
    }
}

#[pyclass]
// struct and field are pub for consumption in pants_ng.rs.
pub(crate) struct PyOptionId(pub(crate) OptionId);

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
                    "Switch value should contain a single character, but was: {s}"
                )));
            }
        };
        let option_id =
            OptionId::new(scope, components.into_iter(), switch).map_err(ParseError::new_err)?;
        Ok(Self(option_id))
    }
}

#[pyclass]
struct PyPantsCommand(PantsCommand);

#[pymethods]
impl PyPantsCommand {
    fn builtin_or_auxiliary_goal(&self) -> &Option<String> {
        &self.0.builtin_or_auxiliary_goal
    }

    fn goals(&self) -> &Vec<String> {
        &self.0.goals
    }

    fn unknown_goals(&self) -> &Vec<String> {
        &self.0.unknown_goals
    }

    fn specs(&self) -> &Vec<String> {
        &self.0.specs
    }

    fn passthru(&self) -> &Option<Vec<String>> {
        &self.0.passthru
    }
}

#[pyclass]
pub struct PyConfigSource(pub ConfigSource);

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
pub struct PyOptionParser(pub OptionParser);

// The pythonic value of a dict-typed option.
pub(crate) type PyDictVal = HashMap<String, Py<PyAny>>;

// The derivation of the option value, as a vec of (value, rank, details string) tuples.
type OptionValueDerivation<'py, T> = Vec<(T, isize, Option<Bound<'py, PyString>>)>;

// A tuple (final value, rank of final value, optional derivation of value).
//
// Note: The final value and its rank could be computed from the derivation (see above),
// but the full derivation is not itself computed in normal usage.
// We could get rid of this tuple type by representing the final value and its rank as
// a singleton derivation (in the case where we don't otherwise need the full derivation).
// But that would allocate two unnecessary Vecs for every option.
// TODO: Disambiguate from OptionValue in the options crate.
pub(crate) type OptionValue<'py, T> = (Option<T>, isize, Option<OptionValueDerivation<'py, T>>);

fn source_to_details(source: &Source) -> Option<&str> {
    match source {
        Source::Default => None,
        Source::Config { ordinal: _, path } => Some(path),
        Source::Env => Some("env var"),
        Source::Flag => Some("command-line flag"),
    }
}

fn to_details<'py>(py: Python<'py>, sources: Vec<&'py Source>) -> Option<Bound<'py, PyString>> {
    if sources.is_empty() {
        return None;
    }
    if sources.len() == 1 {
        return source_to_details(sources.first().unwrap()).map(|s| PyString::intern(py, s));
    }
    #[allow(unstable_name_collisions)]
    // intersperse is provided by itertools::Itertools, but is also in the Rust nightly
    // as an experimental feature of standard Iterator. If/when that becomes standard we
    // can use it, but for now we must squelch the name collision.
    Some(PyString::intern(
        py,
        &sources
            .into_iter()
            .filter_map(source_to_details)
            .intersperse(", ")
            .collect::<String>(),
    ))
}

// Condense list value derivation across sources, so that it reflects merges vs. replacements
// in a useful way. E.g., if we merge [a, b] and [c], and then replace it with [d, e],
// the derivation will show:
//   - [d, e] (from command-line flag)
//   - [a, b, c] (from env var, from config)
pub(crate) fn condense_list_value_derivation<'py, T: PartialEq>(
    py: Python<'py>,
    derivation: Vec<(&'py Source, Vec<ListEdit<T>>)>,
) -> OptionValueDerivation<'py, Vec<T>> {
    let mut ret: OptionValueDerivation<'py, Vec<T>> = vec![];
    let mut cur_group: Vec<ListEdit<T>> = vec![];
    let mut cur_sources: Vec<&Source> = vec![];

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
                if !cur_sources.is_empty() {
                    ret.push((
                        apply_list_edits::<T>(remover, cur_group.into_iter()),
                        cur_sources.last().unwrap().rank() as isize,
                        to_details(py, cur_sources),
                    ));
                }
                cur_group = vec![];
                cur_sources = vec![];
            }
            cur_group.push(list_edit);
            cur_sources.push(source);
        }
    }
    if !cur_sources.is_empty() {
        ret.push((
            apply_list_edits::<T>(remover, cur_group.into_iter()),
            cur_sources.last().unwrap().rank() as isize,
            to_details(py, cur_sources),
        ));
    }

    ret
}

// Condense dict value derivation across sources, so that it reflects merges vs. replacements
//  in a useful way. E.g., if we merge {a: 1, b: 2] and {c: 3}, and then replace it with {d: 4},
// the derivation will show:
//   - {d: 4} (from command-line flag)
//   - {a: 1, b: 2, c: 3} (from env var, from config)
pub(crate) fn condense_dict_value_derivation<'py>(
    py: Python<'py>,
    derivation: Vec<(&'py Source, Vec<DictEdit>)>,
) -> PyResult<OptionValueDerivation<'py, PyDictVal>> {
    let mut ret: OptionValueDerivation<'py, PyDictVal> = vec![];
    let mut cur_group: Vec<DictEdit> = vec![];
    let mut cur_sources: Vec<&Source> = vec![];

    for (source, dict_edits) in derivation.into_iter() {
        for dict_edit in dict_edits {
            if dict_edit.action == DictEditAction::Replace {
                if !cur_group.is_empty() {
                    ret.push((
                        dict_into_py(py, apply_dict_edits(cur_group.into_iter()))?,
                        cur_sources.last().unwrap().rank() as isize,
                        to_details(py, cur_sources),
                    ));
                }
                cur_group = vec![];
                cur_sources = vec![];
            }
            cur_group.push(dict_edit);
            cur_sources.push(source);
        }
    }
    if !cur_group.is_empty() {
        ret.push((
            dict_into_py(py, apply_dict_edits(cur_group.into_iter()))?,
            cur_sources.last().unwrap().rank() as isize,
            to_details(py, cur_sources),
        ));
    }

    Ok(ret)
}

pub(crate) fn into_py<'py, T>(
    py: Python<'py>,
    res: Result<OptionalOptionValue<'py, T>, String>,
) -> PyResult<OptionValue<'py, T>> {
    let val = res.map_err(ParseError::new_err)?;
    Ok((
        val.value,
        val.source.rank() as isize,
        val.derivation.map(|d| {
            d.into_iter()
                .map(|(source, val)| (val, source.rank() as isize, to_details(py, vec![source])))
                .collect()
        }),
    ))
}

#[allow(clippy::type_complexity)]
impl PyOptionParser {
    fn get_list<'py, T: ToOwned + ?Sized>(
        &'py self,
        py: Python<'py>,
        option_id: &Bound<'_, PyOptionId>,
        default: Vec<T::Owned>,
        getter: fn(
            &'py OptionParser,
            &OptionId,
            Vec<T::Owned>,
        ) -> Result<ListOptionValue<'py, T::Owned>, String>,
    ) -> PyResult<OptionValue<'py, Vec<T::Owned>>>
    where
        <T as ToOwned>::Owned: PartialEq,
    {
        let opt_val =
            getter(&self.0, &option_id.borrow().0, default).map_err(ParseError::new_err)?;
        Ok((
            Some(opt_val.value),
            opt_val.source.rank() as isize,
            opt_val
                .derivation
                .map(|d| condense_list_value_derivation(py, d)),
        ))
    }
}

#[pymethods]
impl PyOptionParser {
    #[new]
    #[pyo3(signature = (buildroot, args, env, configs, allow_pantsrc, include_derivation, known_scopes_to_flags, known_goals))]
    fn __new__<'py>(
        buildroot: Option<PathBuf>,
        args: Vec<String>,
        env: &Bound<'py, PyDict>,
        configs: Option<Vec<Bound<'py, PyConfigSource>>>,
        allow_pantsrc: bool,
        include_derivation: bool,
        known_scopes_to_flags: Option<HashMap<String, HashSet<String>>>,
        known_goals: Option<Vec<Bound<'py, PyGoalInfo>>>,
    ) -> PyResult<Self> {
        let env = env
            .items()
            .into_iter()
            .map(|kv_pair| kv_pair.extract::<(String, String)>())
            .collect::<Result<BTreeMap<_, _>, _>>()?;

        let option_parser = OptionParser::new(
            Args::new(args),
            Env::new(env),
            configs.map(|cs| cs.iter().map(|c| c.borrow().0.clone()).collect()),
            allow_pantsrc,
            include_derivation,
            buildroot.map(BuildRoot::for_path),
            known_scopes_to_flags.as_ref(),
            known_goals.map(|gis| gis.iter().map(|gi| gi.borrow().0.clone()).collect()),
        )
        .map_err(ParseError::new_err)?;
        Ok(Self(option_parser))
    }

    #[pyo3(signature = (option_id, default))]
    fn get_bool<'py>(
        &'py self,
        py: Python<'py>,
        option_id: &Bound<'_, PyOptionId>,
        default: Option<bool>,
    ) -> PyResult<OptionValue<'py, bool>> {
        into_py(
            py,
            self.0.parse_bool_optional(&option_id.borrow().0, default),
        )
    }

    #[pyo3(signature = (option_id, default))]
    fn get_int<'py>(
        &'py self,
        py: Python<'py>,
        option_id: &Bound<'_, PyOptionId>,
        default: Option<i64>,
    ) -> PyResult<OptionValue<'py, i64>> {
        into_py(
            py,
            self.0.parse_int_optional(&option_id.borrow().0, default),
        )
    }

    #[pyo3(signature = (option_id, default))]
    fn get_float<'py>(
        &'py self,
        py: Python<'py>,
        option_id: &Bound<'_, PyOptionId>,
        default: Option<f64>,
    ) -> PyResult<OptionValue<'py, f64>> {
        into_py(
            py,
            self.0.parse_float_optional(&option_id.borrow().0, default),
        )
    }

    #[pyo3(signature = (option_id, default))]
    fn get_string<'py>(
        &'py self,
        py: Python<'py>,
        option_id: &Bound<'_, PyOptionId>,
        default: Option<&str>,
    ) -> PyResult<OptionValue<'py, String>> {
        into_py(
            py,
            self.0.parse_string_optional(&option_id.borrow().0, default),
        )
    }

    fn get_bool_list<'py>(
        &'py self,
        py: Python<'py>,
        option_id: &Bound<'_, PyOptionId>,
        default: Vec<bool>,
    ) -> PyResult<OptionValue<'py, Vec<bool>>> {
        self.get_list::<bool>(py, option_id, default, |op, oid, def| {
            op.parse_bool_list(oid, def)
        })
    }

    fn get_int_list<'py>(
        &'py self,
        py: Python<'py>,
        option_id: &Bound<'_, PyOptionId>,
        default: Vec<i64>,
    ) -> PyResult<OptionValue<'py, Vec<i64>>> {
        self.get_list::<i64>(py, option_id, default, |op, oid, def| {
            op.parse_int_list(oid, def)
        })
    }

    fn get_float_list<'py>(
        &'py self,
        py: Python<'py>,
        option_id: &Bound<'_, PyOptionId>,
        default: Vec<f64>,
    ) -> PyResult<OptionValue<'py, Vec<f64>>> {
        self.get_list::<f64>(py, option_id, default, |op, oid, def| {
            op.parse_float_list(oid, def)
        })
    }

    fn get_string_list<'py>(
        &'py self,
        py: Python<'py>,
        option_id: &Bound<'_, PyOptionId>,
        default: Vec<String>,
    ) -> PyResult<OptionValue<'py, Vec<String>>> {
        self.get_list::<String>(py, option_id, default, |op, oid, def| {
            op.parse_string_list(oid, def)
        })
    }

    fn get_dict<'py>(
        &'py self,
        py: Python<'py>,
        option_id: &Bound<'_, PyOptionId>,
        default: &Bound<'_, PyDict>,
    ) -> PyResult<OptionValue<'py, PyDictVal>> {
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

    fn get_command(&self) -> PyPantsCommand {
        PyPantsCommand(self.0.command.clone())
    }

    fn get_unconsumed_flags(&self) -> PyResult<HashMap<String, Vec<String>>> {
        // The python side expects an empty string to represent the GLOBAL scope.
        Ok(self
            .0
            .get_unconsumed_flags()
            .map_err(PyException::new_err)?
            .into_iter()
            .map(|(k, v)| {
                (
                    (if k.name() == "GLOBAL" { "" } else { k.name() }).to_string(),
                    v,
                )
            })
            .collect())
    }

    fn validate_config(
        &self,
        py: Python<'_>,
        py_valid_keys: HashMap<String, Py<PyAny>>,
    ) -> PyResult<Vec<String>> {
        let mut valid_keys = HashMap::new();

        for (section_name, keys) in py_valid_keys.into_iter() {
            let keys_set = keys.extract::<HashSet<String>>(py)?;
            valid_keys.insert(section_name, keys_set);
        }

        Ok(self.0.validate_config(&valid_keys))
    }
}
