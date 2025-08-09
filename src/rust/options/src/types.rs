// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

/// A primitive enum for option types, containing the default value for the option.
///
/// Currently only used for `pantsd` fingerprinting, which is defined in Rust. Options in general
/// are registered in Python (see in particular `global_options.py`).
pub enum OptionType {
    Bool(bool),
    Int(i64),
    Float(f64),
    String(String),
    StringList(Vec<String>),
    // NB: Notably missing is `Dict`: but that type is not yet supported by the Rust parser.
}

impl From<bool> for OptionType {
    fn from(v: bool) -> Self {
        OptionType::Bool(v)
    }
}

impl From<i64> for OptionType {
    fn from(v: i64) -> Self {
        OptionType::Int(v)
    }
}

impl From<f64> for OptionType {
    fn from(v: f64) -> Self {
        OptionType::Float(v)
    }
}

impl From<&str> for OptionType {
    fn from(v: &str) -> Self {
        OptionType::String(v.to_owned())
    }
}

impl From<String> for OptionType {
    fn from(v: String) -> Self {
        OptionType::String(v)
    }
}

impl From<Vec<&str>> for OptionType {
    fn from(v: Vec<&str>) -> Self {
        OptionType::StringList(v.into_iter().map(|s| s.to_owned()).collect())
    }
}
