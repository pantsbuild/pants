// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::fromfile::FromfileExpander;
use crate::id::NameTransform;
use crate::parse::{ParseError, Parseable};
use crate::{DictEdit, ListEdit, OptionsSource};
use crate::{OptionId, Scope};
use std::any::Any;
use std::collections::HashMap;

// This properly belongs in pants_ng/options/flags.rs, but it depends on a lot of non-public
// code from this crate, so we keep it here for now rather than open up this crate.
pub struct PantsNgFlagsReader {
    // Map from scope to map of name => vals. Multiple vals means that the same
    // flag name was specified multiple times.
    flags: HashMap<Scope, HashMap<String, Vec<Option<String>>>>,
    fromfile_expander: FromfileExpander,
}

impl PantsNgFlagsReader {
    pub fn new(
        flags: HashMap<Scope, HashMap<String, Vec<Option<String>>>>,
        fromfile_expander: FromfileExpander,
    ) -> Self {
        Self {
            flags,
            fromfile_expander,
        }
    }

    fn get_vals(&self, id: &OptionId) -> Option<&Vec<Option<String>>> {
        // TODO: memoize name_underscored() onto OptionId?
        self.flags
            .get(&id.scope)
            .and_then(|hm| hm.get(&id.name_underscored()))
    }

    fn to_bool(&self, val: &Option<String>) -> Result<Option<bool>, ParseError> {
        // An arg can represent a bool either by having an explicit value parseable as a bool,
        // or by having no value (in which case it represents true).
        match val {
            Some(value) => match self.fromfile_expander.expand(value.to_string())? {
                Some(s) => bool::parse(&s).map(Some),
                _ => Ok(None),
            },
            None => Ok(Some(true)),
        }
    }

    fn get_list<T: Parseable>(&self, id: &OptionId) -> Result<Option<Vec<ListEdit<T>>>, String> {
        let mut edits = vec![];
        if let Some(vals) = self.get_vals(id) {
            for opt_val in vals {
                if let Some(val) = opt_val {
                    if let Some(es) = self
                        .fromfile_expander
                        .expand_to_list::<T>(val.to_string())
                        .map_err(|e| e.render(id.name_underscored()))?
                    {
                        edits.extend(es);
                    }
                } else {
                    return Err(format!(
                        "Expected list option {} to have a value.",
                        self.display(id)
                    ));
                }
            }
        }
        if edits.is_empty() {
            Ok(None)
        } else {
            Ok(Some(edits))
        }
    }
}

impl OptionsSource for PantsNgFlagsReader {
    fn display(&self, id: &OptionId) -> String {
        match &id.scope {
            Scope::Global => format!("--{}", id.name("_", NameTransform::ToLower)),
            Scope::Scope(scope) => format!(
                "--{}-{}-",
                scope.to_ascii_lowercase(),
                id.name("_", NameTransform::ToLower)
            ),
        }
    }

    fn as_any(&self) -> &dyn Any {
        self
    }

    fn get_string(&self, id: &OptionId) -> Result<Option<String>, String> {
        if let Some(vals) = self.get_vals(id) {
            // We take the last item, so that the rightmost flag wins.
            if let Some(opt_val) = vals.last() {
                return self
                    .fromfile_expander
                    .expand(opt_val.clone().ok_or_else(|| {
                        format!("Expected list option {} to have a value.", self.display(id))
                    })?)
                    .map_err(|e| e.render(id.name_underscored()));
            }
        }
        Ok(None)
    }

    fn get_bool(&self, id: &OptionId) -> Result<Option<bool>, String> {
        if let Some(vals) = self.get_vals(id) {
            // We take the last item, so that the rightmost flag wins.
            if let Some(opt_val) = vals.last() {
                return self
                    .to_bool(opt_val)
                    .map_err(|e| e.render(id.name_underscored()));
            }
        };
        Ok(None)
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
        let mut edits = vec![];
        if let Some(vals) = self.get_vals(id) {
            for opt_val in vals {
                if let Some(val) = opt_val {
                    if let Some(es) = self
                        .fromfile_expander
                        .expand_to_dict(val.to_string())
                        .map_err(|e| e.render(id.name_underscored()))?
                    {
                        edits.extend(es);
                    }
                } else {
                    return Err(format!(
                        "Expected list option {} to have a value.",
                        self.display(id)
                    ));
                }
            }
        }
        if edits.is_empty() {
            Ok(None)
        } else {
            Ok(Some(edits))
        }
    }
}
