// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::{HashMap, HashSet};
use std::ffi::OsString;
use std::fs;
use std::path::Path;

use lazy_static::lazy_static;
use regex::Regex;
use toml::value::Table;
use toml::Value;

use super::id::{NameTransform, OptionId};
use super::parse::{
    parse_bool_list, parse_dict, parse_float_list, parse_int_list, parse_string_list, ParseError,
};
use super::{DictEdit, DictEditAction, ListEdit, ListEditAction, OptionsSource, Val};

type InterpolationMap = HashMap<String, String>;

lazy_static! {
    static ref PLACEHOLDER_RE: Regex = Regex::new(r"%\(([a-zA-Z0-9_.]+)\)s").unwrap();
}

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
            "Unknown value for placeholder `{}`",
            placeholder_name
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

trait FromValue: Sized {
    fn from_value(value: &Value) -> Result<Self, ValueConversionError>;

    fn from_config(config: &Config, id: &OptionId) -> Result<Option<Self>, String> {
        if let Some(value) = config.get_value(id) {
            match Self::from_value(value) {
                Ok(x) => Ok(Some(x)),
                Err(verr) => Err(format!(
                    "Expected {id} to be a {} but given {}",
                    verr.expected_type, verr.given_value
                )),
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
    fn from_value(value: &Value) -> Result<String, ValueConversionError> {
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
    fn from_value(value: &Value) -> Result<bool, ValueConversionError> {
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
    fn from_value(value: &Value) -> Result<i64, ValueConversionError> {
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
    fn from_value(value: &Value) -> Result<f64, ValueConversionError> {
        if let Some(float) = value.as_float() {
            Ok(float)
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

#[derive(Clone)]
struct ConfigSource {
    #[allow(dead_code)]
    path: Option<OsString>,
    config: Value,
}

impl ConfigSource {
    fn option_name(id: &OptionId) -> String {
        id.name("_", NameTransform::None)
    }

    fn get_value(&self, id: &OptionId) -> Option<&Value> {
        self.config
            .get(id.scope())
            .and_then(|table| table.get(Self::option_name(id)))
    }

    fn get_list<T: FromValue>(
        &self,
        id: &OptionId,
        parse_list: fn(&str) -> Result<Vec<ListEdit<T>>, ParseError>,
    ) -> Result<Vec<ListEdit<T>>, String> {
        let mut list_edits = vec![];
        if let Some(table) = self.config.get(id.scope()) {
            let option_name = Self::option_name(id);
            if let Some(value) = table.get(&option_name) {
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
                            })
                        }
                        if let Some(remove) = sub_table.get("remove") {
                            list_edits.push(ListEdit {
                                action: ListEditAction::Remove,
                                items: T::extract_list(&format!("{option_name}.remove"), remove)?,
                            })
                        }
                    }
                    Value::String(v) => {
                        list_edits.extend(parse_list(v).map_err(|e| e.render(option_name))?);
                    }
                    value => list_edits.push(ListEdit {
                        action: ListEditAction::Replace,
                        items: T::extract_list(&option_name, value)?,
                    }),
                }
            }
        }
        Ok(list_edits)
    }

    fn get_dict(&self, id: &OptionId) -> Result<Option<DictEdit>, String> {
        if let Some(table) = self.config.get(id.scope()) {
            let option_name = Self::option_name(id);
            if let Some(value) = table.get(&option_name) {
                match value {
                    Value::Table(sub_table) => {
                        if let Some(add) = sub_table.get("add") {
                            if sub_table.len() == 1 && add.is_table() {
                                return Ok(Some(DictEdit {
                                    action: DictEditAction::Add,
                                    items: toml_table_to_dict(add),
                                }));
                            }
                        }
                        return Ok(Some(DictEdit {
                            action: DictEditAction::Replace,
                            items: toml_table_to_dict(value),
                        }));
                    }
                    Value::String(v) => {
                        return Ok(Some(parse_dict(v).map_err(|e| e.render(option_name))?));
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

#[derive(Clone)]
pub(crate) struct Config {
    sources: Vec<ConfigSource>,
}

impl Config {
    pub(crate) fn parse<P: AsRef<Path>>(
        files: &[P],
        seed_values: &InterpolationMap,
    ) -> Result<Config, String> {
        let mut sources = vec![];
        for file in files {
            sources.push(Self::parse_source(file, seed_values)?);
        }
        Ok(Config { sources })
    }

    pub(crate) fn merge(self, other: Config) -> Config {
        Config {
            sources: self.sources.into_iter().chain(other.sources).collect(),
        }
    }

    fn parse_source<P: AsRef<Path>>(
        file: P,
        seed_values: &InterpolationMap,
    ) -> Result<ConfigSource, String> {
        let config_contents = fs::read_to_string(&file).map_err(|e| {
            format!(
                "Failed to read config file {}: {}",
                file.as_ref().display(),
                e
            )
        })?;
        let config = config_contents.parse::<Value>().map_err(|e| {
            format!(
                "Failed to parse config file {}: {}",
                file.as_ref().display(),
                e
            )
        })?;

        fn add_section_to_interpolation_map(
            mut imap: InterpolationMap,
            section: Option<&Value>,
        ) -> Result<InterpolationMap, String> {
            if let Some(section) = section {
                if let Some(table) = section.as_table() {
                    for (key, value) in table.iter() {
                        if let Value::String(s) = value {
                            imap.insert(key.clone(), s.clone());
                        }
                    }
                }
            }
            Ok(imap)
        }

        let default_imap =
            add_section_to_interpolation_map(seed_values.clone(), config.get("DEFAULT"))?;

        let new_sections: Result<Vec<(String, Value)>, String> = match config {
            Value::Table(t) => t
                .into_iter()
                .map(|(section_name, section)| {
                    if !section.is_table() {
                        return Err(format!(
                            "Expected the config file {} to contain tables per section, \
                            but section {} contained a {}: {}",
                            file.as_ref().display(),
                            section_name,
                            section.type_str(),
                            section
                        ));
                    }
                    let section_imap = if section_name == "DEFAULT" {
                        default_imap.clone()
                    } else {
                        add_section_to_interpolation_map(default_imap.clone(), Some(&section))?
                    };
                    let new_section = interpolate_value("", section.clone(), &section_imap)
                        .map_err(|e| {
                            format!(
                                "{} in config file {}, section {}, key {}",
                                e.msg,
                                file.as_ref().display(),
                                section_name,
                                e.key
                            )
                        })?;
                    Ok((section_name, new_section))
                })
                .collect(),

            _ => Err(format!(
                "Expected the config file {} to contain a table but contained a {}: {}",
                file.as_ref().display(),
                config.type_str(),
                config
            )),
        };

        let new_table = Table::from_iter(new_sections?);
        Ok(ConfigSource {
            path: Some(file.as_ref().as_os_str().into()),
            config: Value::Table(new_table),
        })
    }

    fn get_value(&self, id: &OptionId) -> Option<&Value> {
        self.sources
            .iter()
            .rev()
            .find_map(|source| source.get_value(id))
    }

    fn get_list<T: FromValue>(
        &self,
        id: &OptionId,
        parse_list: fn(&str) -> Result<Vec<ListEdit<T>>, ParseError>,
    ) -> Result<Option<Vec<ListEdit<T>>>, String> {
        let mut edits: Vec<ListEdit<T>> = vec![];
        for source in self.sources.iter() {
            edits.append(&mut source.get_list(id, parse_list)?);
        }
        Ok(Some(edits))
    }
}

impl OptionsSource for Config {
    fn display(&self, id: &OptionId) -> String {
        format!("{id}")
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
        self.get_list(id, parse_bool_list)
    }

    fn get_int_list(&self, id: &OptionId) -> Result<Option<Vec<ListEdit<i64>>>, String> {
        self.get_list(id, parse_int_list)
    }

    fn get_float_list(&self, id: &OptionId) -> Result<Option<Vec<ListEdit<f64>>>, String> {
        self.get_list(id, parse_float_list)
    }

    fn get_string_list(&self, id: &OptionId) -> Result<Option<Vec<ListEdit<String>>>, String> {
        self.get_list(id, parse_string_list)
    }

    fn get_dict(&self, id: &OptionId) -> Result<Option<Vec<DictEdit>>, String> {
        let mut edits = vec![];
        for source in self.sources.iter() {
            if let Some(edit) = source.get_dict(id)? {
                edits.push(edit);
            }
        }
        Ok(if edits.is_empty() { None } else { Some(edits) })
    }
}
