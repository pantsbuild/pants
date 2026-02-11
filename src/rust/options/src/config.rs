// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::any::Any;
use std::collections::{BTreeMap, HashMap, HashSet};
use std::fs;
use std::hash::Hash;
use std::path::{Path, PathBuf};
use std::sync::LazyLock;

use regex::Regex;
use sha2::Sha256;
use sha2::digest::Update;
use toml::Value;
use toml::value::Table;

use super::{DictEdit, DictEditAction, ListEdit, ListEditAction, OptionsSource, Val};
use crate::fromfile::FromfileExpander;
use crate::id::{NameTransform, OptionId};
use crate::parse::Parseable;

type InterpolationMap = BTreeMap<String, String>;

static DEFAULT_SECTION: &str = "DEFAULT";

static PLACEHOLDER_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"%\(([a-zA-Z0-9_.]+)\)s").unwrap());

pub(crate) fn interpolate_string(
    value: String,
    replacements: &InterpolationMap,
) -> Result<String, String> {
    let caps_vec: Vec<_> = PLACEHOLDER_RE.captures_iter(&value).collect();
    if caps_vec.is_empty() {
        return Ok(value);
    }

    let mut new_value = String::with_capacity(value.len());
    let mut last_match = 0;
    for caps in caps_vec {
        let m = caps.get(0).unwrap();
        new_value.push_str(&value[last_match..m.start()]);
        let placeholder_name = &caps[1];
        let replacement = replacements.get(placeholder_name).ok_or(format!(
            "Unknown value for placeholder `{placeholder_name}`"
        ))?;
        new_value.push_str(replacement);
        last_match = m.end();
    }
    new_value.push_str(&value[last_match..]);
    // A replacement string may itself contain a placeholder, so we recurse.
    interpolate_string(new_value, replacements)
}

struct InterpolationError {
    key: String,
    msg: String,
}

fn interpolate_value(
    key: &str,
    value: Value,
    replacements: &InterpolationMap,
) -> Result<Value, InterpolationError> {
    Ok(match value {
        Value::String(s) => Value::String(interpolate_string(s, replacements).map_err(|msg| {
            InterpolationError {
                key: key.to_string(),
                msg,
            }
        })?),
        Value::Array(v) => {
            let new_v: Result<Vec<_>, _> = v
                .into_iter()
                .map(|x| interpolate_value(key, x, replacements))
                .collect();
            Value::Array(new_v?)
        }
        Value::Table(t) => {
            let new_items: Result<Vec<_>, _> = t
                .into_iter()
                .map(|(k, v)| {
                    match interpolate_value(
                        // Use the section-level key even if this is a nested table value.
                        if key.is_empty() { &k } else { key },
                        v,
                        replacements,
                    ) {
                        Ok(new_v) => Ok((k, new_v)),
                        Err(s) => Err(s),
                    }
                })
                .collect();
            Value::Table(new_items?.into_iter().collect())
        }
        _ => value,
    })
}

struct ValueConversionError<'a> {
    expected_type: &'static str,
    given_value: &'a Value,
}

trait FromValue: Parseable {
    fn from_value(value: &Value) -> Result<Self, ValueConversionError<'_>>;

    fn from_config(config: &ConfigReader, id: &OptionId) -> Result<Option<Self>, String> {
        if let Some(value) = config.get_value(id) {
            if value.is_str() {
                match config
                    .fromfile_expander
                    .expand(value.as_str().unwrap().to_owned())
                    .map_err(|e| e.render(config.display(id)))?
                {
                    Some(expanded_value) => Ok(Some(
                        Self::parse(&expanded_value).map_err(|e| e.render(config.display(id)))?,
                    )),
                    _ => Ok(None),
                }
            } else {
                match Self::from_value(value) {
                    Ok(x) => Ok(Some(x)),
                    Err(verr) => Err(format!(
                        "Expected {id} to be a {} but given {}",
                        verr.expected_type, verr.given_value
                    )),
                }
            }
        } else {
            Ok(None)
        }
    }

    fn extract_list(option_name: &str, value: &Value) -> Result<Vec<Self>, String> {
        if let Some(array) = value.as_array() {
            let mut items = vec![];
            for item in array {
                items.push(Self::from_value(item).map_err(|verr|
                    format!(
                        "Expected {option_name} to be an array of {0}s but given {value} containing \
                        non-{0} item {item}", verr.expected_type
                    ))?);
            }
            Ok(items)
        } else {
            Err(format!(
                "Expected {option_name} to be a toml array or Python sequence, but given {value}."
            ))
        }
    }
}

impl FromValue for String {
    fn from_value(value: &Value) -> Result<String, ValueConversionError<'_>> {
        if let Some(string) = value.as_str() {
            Ok(string.to_owned())
        } else {
            Err(ValueConversionError {
                expected_type: "string",
                given_value: value,
            })
        }
    }
}

impl FromValue for bool {
    fn from_value(value: &Value) -> Result<bool, ValueConversionError<'_>> {
        if let Some(boolean) = value.as_bool() {
            Ok(boolean)
        } else {
            Err(ValueConversionError {
                expected_type: "bool",
                given_value: value,
            })
        }
    }
}

impl FromValue for i64 {
    fn from_value(value: &Value) -> Result<i64, ValueConversionError<'_>> {
        if let Some(int) = value.as_integer() {
            Ok(int)
        } else {
            Err(ValueConversionError {
                expected_type: "int",
                given_value: value,
            })
        }
    }
}

impl FromValue for f64 {
    fn from_value(value: &Value) -> Result<f64, ValueConversionError<'_>> {
        if let Some(float) = value.as_float() {
            Ok(float)
        } else if let Some(int) = value.as_integer() {
            // See if we can parse as an int and coerce it to a float.
            Ok(int as f64)
        } else {
            Err(ValueConversionError {
                expected_type: "float",
                given_value: value,
            })
        }
    }
}

fn toml_value_to_val(value: &Value) -> Val {
    match value {
        Value::String(s) => Val::String(s.to_owned()),
        Value::Integer(i) => Val::Int(*i),
        Value::Float(f) => Val::Float(*f),
        Value::Boolean(b) => Val::Bool(*b),
        Value::Datetime(d) => Val::String(d.to_string()),
        Value::Array(a) => Val::List(a.iter().map(toml_value_to_val).collect()),
        Value::Table(t) => Val::Dict(
            t.iter()
                .map(|(k, v)| (k.to_string(), toml_value_to_val(v)))
                .collect(),
        ),
    }
}

// Helper function. Only call if you know that the arg is a Value::Table.
fn toml_table_to_dict(table: &Value) -> HashMap<String, Val> {
    if !table.is_table() {
        panic!("Expected a TOML table but received: {table}");
    }
    if let Val::Dict(hm) = toml_value_to_val(table) {
        hm
    } else {
        panic!("toml_value_to_val() on a Value::Table must return a Val::Dict");
    }
}

#[derive(Clone, Debug)]
pub struct ConfigSource {
    pub path: PathBuf,
    pub content: String,
}

impl ConfigSource {
    pub fn from_file<P: AsRef<Path>>(path: P) -> Result<ConfigSource, String> {
        let content = fs::read_to_string(&path).map_err(|e| {
            format!(
                "Failed to read config file {}: {}",
                path.as_ref().display(),
                e
            )
        })?;
        Ok(ConfigSource {
            path: path.as_ref().to_path_buf(),
            content,
        })
    }
}

#[derive(Clone, Debug)]
pub struct Config {
    value: Value,
}

// Value doesn't implement Eq and Hash because of floats, but in our case we can insist that
// NaN == NaN for config equality/hash purposes. For one thing, we don't meaningfully
// support NaN in config values (although we don't enforce that they don't appear).
// For another, if NaN != NaN then we must invalidate that config on every run,
// which is very unlikely to be what the user intends.

fn _eq_toml_value(left: &Value, right: &Value) -> bool {
    match left {
        Value::String(s0) => {
            if let Value::String(s1) = right {
                s0 == s1
            } else {
                false
            }
        }
        Value::Integer(i0) => {
            if let Value::Integer(i1) = right {
                i0 == i1
            } else {
                false
            }
        }
        Value::Float(f0) => {
            if let Value::Float(f1) = right {
                f0.to_bits() == f1.to_bits()
            } else {
                false
            }
        }
        Value::Boolean(b0) => {
            if let Value::Boolean(b1) = right {
                b0 == b1
            } else {
                false
            }
        }
        Value::Datetime(d0) => {
            if let Value::Datetime(d1) = right {
                d0 == d1
            } else {
                false
            }
        }
        Value::Array(a0) => {
            if let Value::Array(a1) = right {
                a0.len() == a1.len()
                    && a0
                        .iter()
                        .zip(a1.iter())
                        .all(|(v0, v1)| _eq_toml_value(v0, v1))
            } else {
                false
            }
        }
        // We use the preserve_order feature, so we'll get the table entries in a consistent order.
        Value::Table(t0) => {
            if let Value::Table(t1) = right {
                t0.len() == t1.len()
                    && t0
                        .iter()
                        .zip(t1.iter())
                        .all(|(e0, e1)| e0.0 == e1.0 && _eq_toml_value(e0.1, e1.1))
            } else {
                false
            }
        }
    }
}

impl PartialEq for Config {
    fn eq(&self, other: &Self) -> bool {
        _eq_toml_value(&self.value, &other.value)
    }
}

impl Eq for Config {}

fn _hash_toml_value<H: std::hash::Hasher>(value: &Value, state: &mut H) {
    match value {
        Value::String(s) => s.hash(state),
        Value::Integer(i) => i.hash(state),
        Value::Float(f) => state.write_u64(f.to_bits()),
        Value::Boolean(b) => b.hash(state),
        // We don't support datetime types in config, so we won't incur this to_string() cost
        // in practice.
        Value::Datetime(dt) => dt.to_string().hash(state),
        Value::Array(a) => {
            for m in a {
                _hash_toml_value(m, state);
            }
        }
        // We use the preserve_order feature, so we'll get the table entries in a consistent order.
        Value::Table(t) => {
            for (k, v) in t.iter() {
                k.hash(state);
                _hash_toml_value(v, state);
            }
        }
    }
}

impl Hash for Config {
    fn hash<H: std::hash::Hasher>(&self, state: &mut H) {
        _hash_toml_value(&self.value, state);
    }
}

fn add_to_sha256(value: &Value, hasher: &mut Sha256) {
    match value {
        Value::String(s) => hasher.update(s.as_bytes()),
        Value::Integer(i) => hasher.update(&i.to_le_bytes()),
        Value::Float(f) => hasher.update(&f.to_le_bytes()),
        Value::Boolean(b) => hasher.update(&(if *b { [b'1'] } else { [b'0'] })),
        // We don't support datetime types in config, so we won't incur this to_string() cost
        // in practice.
        Value::Datetime(dt) => hasher.update(dt.to_string().as_bytes()),
        Value::Array(a) => {
            for m in a {
                add_to_sha256(m, hasher);
            }
        }
        // We use the preserve_order feature, so we'll get the table entries in a consistent order.
        Value::Table(t) => {
            for (k, v) in t.iter() {
                hasher.update(k.as_bytes());
                add_to_sha256(v, hasher);
            }
        }
    }
}

impl Config {
    pub fn parse(
        config_source: &ConfigSource,
        seed_values: &InterpolationMap,
    ) -> Result<Config, String> {
        let config = config_source.content.parse::<Value>().map_err(|e| {
            format!(
                "Failed to parse config file {}: {}",
                config_source.path.display(),
                e
            )
        })?;

        fn add_section_to_interpolation_map(
            mut imap: InterpolationMap,
            section: Option<&Value>,
        ) -> Result<InterpolationMap, String> {
            if let Some(section) = section
                && let Some(table) = section.as_table()
            {
                for (key, value) in table.iter() {
                    if let Value::String(s) = value {
                        imap.insert(key.clone(), s.clone());
                    }
                }
            }
            Ok(imap)
        }

        let default_imap =
            add_section_to_interpolation_map(seed_values.clone(), config.get(DEFAULT_SECTION))?;

        let new_sections: Result<Vec<(String, Value)>, String> = match config {
            Value::Table(t) => t
                .into_iter()
                .map(|(section_name, section)| {
                    if !section.is_table() {
                        return Err(format!(
                            "Expected the config file {} to contain tables per section, \
                            but section {} contained a {}: {}",
                            config_source.path.display(),
                            section_name,
                            section.type_str(),
                            section
                        ));
                    }
                    let section_imap = if section_name == *DEFAULT_SECTION {
                        default_imap.clone()
                    } else {
                        add_section_to_interpolation_map(default_imap.clone(), Some(&section))?
                    };
                    let new_section = interpolate_value("", section.clone(), &section_imap)
                        .map_err(|e| {
                            format!(
                                "{} in config file {}, section {}, key {}",
                                e.msg,
                                config_source.path.display(),
                                section_name,
                                e.key
                            )
                        })?;
                    Ok((section_name, new_section))
                })
                .collect(),

            _ => Err(format!(
                "Expected the config file {} to contain a table but contained a {}: {}",
                config_source.path.display(),
                config.type_str(),
                config
            )),
        };

        let new_table = Table::from_iter(new_sections?);
        Ok(Self {
            value: Value::Table(new_table),
        })
    }

    pub fn add_to_sha256(&self, hasher: &mut Sha256) {
        add_to_sha256(&self.value, hasher);
    }
}

pub struct ConfigReader {
    config: Config,
    fromfile_expander: FromfileExpander,
}

impl ConfigReader {
    pub fn new(config: Config, fromfile_expander: FromfileExpander) -> Self {
        Self {
            config,
            fromfile_expander,
        }
    }

    pub fn add_to_sha256(&self, hasher: &mut Sha256) {
        self.config.add_to_sha256(hasher);
    }

    // Given a map from section name to valid keys for that section,
    // returns a vec of validation error messages.
    pub fn validate(
        &self,
        section_to_valid_keys: &HashMap<String, HashSet<String>>,
    ) -> Vec<String> {
        let mut errors = vec![];
        // We validated that the top level is a table when creating the Config instances.
        let top_level_table = self.config.value.as_table().unwrap();
        for (section_name, section_table) in top_level_table.iter() {
            // We don't validate the DEFAULT section.
            if section_name == DEFAULT_SECTION {
                continue;
            }
            // We validated that each section is a table when creating the Config instance.
            let section_table = section_table.as_table().unwrap();
            match section_to_valid_keys.get(section_name) {
                None => {
                    errors.push(format!("Invalid table name [{section_name}]"));
                }
                Some(valid_keys) => {
                    for key in section_table.keys() {
                        if !(valid_keys.contains(key)) {
                            errors.push(format!("Invalid option '{key}' under [{section_name}]"));
                        }
                    }
                }
            }
        }
        errors
    }

    fn option_name(id: &OptionId) -> String {
        id.name("_", NameTransform::None)
    }

    fn get_from_section(&self, section_name: &str, option_name: &str) -> Option<&Value> {
        self.config
            .value
            .get(section_name)
            .and_then(|table| table.get(option_name))
    }

    fn get_value(&self, id: &OptionId) -> Option<&Value> {
        let option_name = Self::option_name(id);
        self.get_from_section(id.scope.name(), &option_name)
            .or(self.get_from_section(DEFAULT_SECTION, &option_name))
    }

    fn get_list<T: FromValue + Parseable>(
        &self,
        id: &OptionId,
    ) -> Result<Option<Vec<ListEdit<T>>>, String> {
        let from_scoped_section_opt = self.get_list_from_section(id.scope.name(), id)?;

        Ok(
            if let Some(from_default_section) = self.get_list_from_section(DEFAULT_SECTION, id)? {
                Some(itertools::concat([
                    from_default_section,
                    from_scoped_section_opt.unwrap_or(vec![]),
                ]))
            } else {
                from_scoped_section_opt
            },
        )
    }

    fn get_list_from_section<T: FromValue + Parseable>(
        &self,
        section_name: &str,
        id: &OptionId,
    ) -> Result<Option<Vec<ListEdit<T>>>, String> {
        let mut list_edits = vec![];
        if let Some(table) = self.config.value.get(section_name) {
            let option_name = &Self::option_name(id);
            if let Some(value) = table.get(option_name) {
                match value {
                    Value::Table(sub_table) => {
                        if sub_table.is_empty()
                            || !sub_table.keys().collect::<HashSet<_>>().is_subset(
                                &["add".to_owned(), "remove".to_owned()]
                                    .iter()
                                    .collect::<HashSet<_>>(),
                            )
                        {
                            return Err(format!(
                                "Expected {option_name} to contain an 'add' element, a 'remove' element or both but found: {sub_table:?}"
                            ));
                        }
                        if let Some(add) = sub_table.get("add") {
                            list_edits.push(ListEdit {
                                action: ListEditAction::Add,
                                items: T::extract_list(&format!("{option_name}.add"), add)?,
                            });
                        }
                        if let Some(remove) = sub_table.get("remove") {
                            list_edits.push(ListEdit {
                                action: ListEditAction::Remove,
                                items: T::extract_list(&format!("{option_name}.remove"), remove)?,
                            });
                        }
                    }
                    Value::String(v) => {
                        if let Some(es) = self
                            .fromfile_expander
                            .expand_to_list::<T>(v.to_string())
                            .map_err(|e| e.render(self.display(id)))?
                        {
                            list_edits.extend(es);
                        }
                    }
                    value => list_edits.push(ListEdit {
                        action: ListEditAction::Replace,
                        items: T::extract_list(option_name, value)?,
                    }),
                }
            }
        }

        Ok(if list_edits.is_empty() {
            None
        } else {
            Some(list_edits)
        })
    }

    fn get_dict_from_section(
        &self,
        section_name: &str,
        id: &OptionId,
    ) -> Result<Option<Vec<DictEdit>>, String> {
        if let Some(table) = self.config.value.get(section_name) {
            let option_name = Self::option_name(id);
            if let Some(value) = table.get(&option_name) {
                match value {
                    Value::Table(sub_table) => {
                        if let Some(add) = sub_table.get("add")
                            && sub_table.len() == 1
                            && add.is_table()
                        {
                            return Ok(Some(vec![DictEdit {
                                action: DictEditAction::Add,
                                items: toml_table_to_dict(add),
                            }]));
                        }
                        return Ok(Some(vec![DictEdit {
                            action: DictEditAction::Replace,
                            items: toml_table_to_dict(value),
                        }]));
                    }
                    Value::String(v) => {
                        return self
                            .fromfile_expander
                            .expand_to_dict(v.to_owned())
                            .map_err(|e| e.render(self.display(id)));
                    }
                    _ => {
                        return Err(format!(
                            "Expected {option_name} to be a toml table or Python dict, but given {value}."
                        ));
                    }
                }
            }
        }
        Ok(None)
    }
}

impl OptionsSource for ConfigReader {
    fn display(&self, id: &OptionId) -> String {
        format!("{id}")
    }

    fn as_any(&self) -> &dyn Any {
        self
    }

    fn get_string(&self, id: &OptionId) -> Result<Option<String>, String> {
        String::from_config(self, id)
    }

    fn get_bool(&self, id: &OptionId) -> Result<Option<bool>, String> {
        bool::from_config(self, id)
    }

    fn get_int(&self, id: &OptionId) -> Result<Option<i64>, String> {
        i64::from_config(self, id)
    }

    fn get_float(&self, id: &OptionId) -> Result<Option<f64>, String> {
        f64::from_config(self, id)
    }

    fn get_bool_list(&self, id: &OptionId) -> Result<Option<Vec<ListEdit<bool>>>, String> {
        self.get_list::<bool>(id)
    }

    fn get_int_list(&self, id: &OptionId) -> Result<Option<Vec<ListEdit<i64>>>, String> {
        self.get_list::<i64>(id)
    }

    fn get_float_list(&self, id: &OptionId) -> Result<Option<Vec<ListEdit<f64>>>, String> {
        self.get_list::<f64>(id)
    }

    fn get_string_list(&self, id: &OptionId) -> Result<Option<Vec<ListEdit<String>>>, String> {
        self.get_list::<String>(id)
    }

    fn get_dict(&self, id: &OptionId) -> Result<Option<Vec<DictEdit>>, String> {
        let from_scoped_section_opt = self.get_dict_from_section(id.scope.name(), id)?;

        Ok(
            if let Some(from_default_section) = self.get_dict_from_section(DEFAULT_SECTION, id)? {
                Some(itertools::concat([
                    from_default_section,
                    from_scoped_section_opt.unwrap_or(vec![]),
                ]))
            } else {
                from_scoped_section_opt
            },
        )
    }
}
