// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::{HashMap, HashSet};
use std::fs;
use std::mem;
use std::path::Path;

use lazy_static::lazy_static;
use regex::Regex;
use toml::value::Table;
use toml::Value;

use super::id::{NameTransform, OptionId};
use super::parse::parse_string_list;
use super::{ListEdit, ListEditAction, OptionsSource};

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

#[derive(Clone)]
pub(crate) struct Config {
    config: Value,
}

impl Config {
    pub(crate) fn default() -> Config {
        Config {
            config: Value::Table(Table::new()),
        }
    }

    pub(crate) fn parse<P: AsRef<Path>>(
        file: P,
        seed_values: &InterpolationMap,
    ) -> Result<Config, String> {
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
            imap: &InterpolationMap,
            section: Option<&Value>,
        ) -> Result<InterpolationMap, String> {
            let mut imap = imap.clone();
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

        let default_imap = add_section_to_interpolation_map(seed_values, config.get("DEFAULT"))?;

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
                        add_section_to_interpolation_map(&default_imap, Some(&section))?
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
        Ok(Config {
            config: Value::Table(new_table),
        })
    }

    pub(crate) fn merged<P: AsRef<Path>>(
        files: &[P],
        seed_values: &InterpolationMap,
    ) -> Result<Config, String> {
        files
            .iter()
            .map(|f| Config::parse(f, seed_values))
            .try_fold(Config::default(), |config, parse_result| {
                parse_result.map(|parsed| config.merge(parsed))
            })
    }

    fn option_name(id: &OptionId) -> String {
        id.name("_", NameTransform::None)
    }

    fn extract_string_list(option_name: &str, value: &Value) -> Result<Vec<String>, String> {
        if let Some(array) = value.as_array() {
            let mut items = vec![];
            for item in array {
                if let Some(value) = item.as_str() {
                    items.push(value.to_owned())
                } else {
                    return Err(format!(
            "Expected {option_name} to be an array of strings but given {value} containing non string item {item}"
          ));
                }
            }
            Ok(items)
        } else {
            Err(format!(
                "Expected {option_name} to be a toml array or Python sequence, but given {value}."
            ))
        }
    }

    fn get_value(&self, id: &OptionId) -> Option<&Value> {
        self.config
            .get(id.scope())
            .and_then(|table| table.get(Self::option_name(id)))
    }

    pub(crate) fn merge(mut self, mut other: Config) -> Config {
        let mut map = mem::take(self.config.as_table_mut().unwrap());
        let mut other = mem::take(other.config.as_table_mut().unwrap());
        // Merge overlapping sections.
        for (scope, table) in &mut map {
            if let Some(mut other_table) = other.remove(scope) {
                table
                    .as_table_mut()
                    .unwrap()
                    .extend(mem::take(other_table.as_table_mut().unwrap()));
            }
        }
        // And then extend non-overlapping sections.
        map.extend(other);
        Config {
            config: Value::Table(map),
        }
    }
}

impl OptionsSource for Config {
    fn display(&self, id: &OptionId) -> String {
        format!("{id}")
    }

    fn get_string(&self, id: &OptionId) -> Result<Option<String>, String> {
        if let Some(value) = self.get_value(id) {
            if let Some(string) = value.as_str() {
                Ok(Some(string.to_owned()))
            } else {
                Err(format!("Expected {id} to be a string but given {value}."))
            }
        } else {
            Ok(None)
        }
    }

    fn get_bool(&self, id: &OptionId) -> Result<Option<bool>, String> {
        if let Some(value) = self.get_value(id) {
            if let Some(bool) = value.as_bool() {
                Ok(Some(bool))
            } else {
                Err(format!("Expected {id} to be a bool but given {value}."))
            }
        } else {
            Ok(None)
        }
    }

    fn get_int(&self, id: &OptionId) -> Result<Option<i64>, String> {
        if let Some(value) = self.get_value(id) {
            if let Some(int) = value.as_integer() {
                Ok(Some(int))
            } else {
                Err(format!("Expected {id} to be an int but given {value}."))
            }
        } else {
            Ok(None)
        }
    }

    fn get_float(&self, id: &OptionId) -> Result<Option<f64>, String> {
        if let Some(value) = self.get_value(id) {
            if let Some(float) = value.as_float() {
                Ok(Some(float))
            } else {
                Err(format!("Expected {id} to be a float but given {value}."))
            }
        } else {
            Ok(None)
        }
    }

    fn get_string_list(&self, id: &OptionId) -> Result<Option<Vec<ListEdit<String>>>, String> {
        if let Some(table) = self.config.get(id.scope()) {
            let option_name = Self::option_name(id);
            let mut list_edits = vec![];
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
                                items: Self::extract_string_list(
                                    &format!("{option_name}.add"),
                                    add,
                                )?,
                            })
                        }
                        if let Some(remove) = sub_table.get("remove") {
                            list_edits.push(ListEdit {
                                action: ListEditAction::Remove,
                                items: Self::extract_string_list(
                                    &format!("{option_name}.remove"),
                                    remove,
                                )?,
                            })
                        }
                    }
                    Value::String(v) => {
                        list_edits.extend(parse_string_list(v).map_err(|e| e.render(option_name))?);
                    }
                    value => list_edits.push(ListEdit {
                        action: ListEditAction::Replace,
                        items: Self::extract_string_list(&option_name, value)?,
                    }),
                }
            }
            if !list_edits.is_empty() {
                return Ok(Some(list_edits));
            }
        }
        Ok(None)
    }
}
