// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#![deny(warnings)]
// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![deny(
    clippy::all,
    clippy::default_trait_access,
    clippy::expl_impl_clone_on_copy,
    clippy::if_not_else,
    clippy::needless_continue,
    clippy::unseparated_literal_suffix,
    clippy::used_underscore_binding
)]
// It is often more clear to show that nothing is being moved.
#![allow(clippy::match_ref_pats)]
// Subjective style.
#![allow(
    clippy::len_without_is_empty,
    clippy::redundant_field_names,
    clippy::too_many_arguments
)]
// Default isn't as big a deal as people seem to think it is.
#![allow(clippy::new_without_default, clippy::new_ret_no_self)]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![allow(clippy::mutex_atomic)]

mod args;
#[cfg(test)]
mod args_tests;

mod build_root;
#[cfg(test)]
mod build_root_tests;

mod config;
#[cfg(test)]
mod config_tests;

mod env;
#[cfg(test)]
mod env_tests;

mod id;
#[cfg(test)]
mod id_tests;

mod parse;
#[cfg(test)]
mod parse_tests;

use std::collections::{BTreeMap, HashSet};
use std::ops::Deref;
use std::os::unix::ffi::OsStrExt;
use std::path::Path;
use std::rc::Rc;

use self::args::Args;
use self::config::Config;
use self::env::Env;
pub use build_root::BuildRoot;
pub use id::{OptionId, Scope};

#[derive(Copy, Clone, Debug, Eq, PartialEq)]
pub(crate) enum ListEditAction {
    Replace,
    Add,
    Remove,
}

#[derive(Debug, Eq, PartialEq)]
pub(crate) struct ListEdit<T> {
    pub action: ListEditAction,
    pub items: Vec<T>,
}

///
/// A source of option values.
///
/// This is currently a subset of the types of options the Pants python option system handles.
/// Implementations should mimic the behavior of the equivalent python source.
///
pub(crate) trait OptionsSource {
    ///
    /// Get a display version of the option `id` that most closely matches the syntax used to supply
    /// the id at runtime. For example, an global option of "bob" would display as "--bob" for use in
    /// flag based options and "BOB" in environment variable based options.
    ///
    fn display(&self, id: &OptionId) -> String;

    ///
    /// Get the string option identified by `id` from this source.
    /// Errors when this source has an option value for `id` but that value is not a string.
    ///
    fn get_string(&self, id: &OptionId) -> Result<Option<String>, String>;

    ///
    /// Get the boolean option identified by `id` from this source.
    /// Errors when this source has an option value for `id` but that value is not a boolean.
    ///
    fn get_bool(&self, id: &OptionId) -> Result<Option<bool>, String>;

    ///
    /// Get the float option identified by `id` from this source.
    /// Errors when this source has an option value for `id` but that value is not a float.
    ///
    /// The default implementation looks for a string value for `id` and then attempts to parse it as
    /// a float value.
    ///
    fn get_float(&self, id: &OptionId) -> Result<Option<f64>, String> {
        if let Some(value) = self.get_string(id)? {
            value.parse().map(Some).map_err(|e| {
                format!(
                    "Problem parsing {} value {} as a float value: {}",
                    self.display(id),
                    value,
                    e
                )
            })
        } else {
            Ok(None)
        }
    }

    ///
    /// Get the string list option identified by `id` from this source.
    /// Errors when this source has an option value for `id` but that value is not a string list.
    ///
    fn get_string_list(&self, id: &OptionId) -> Result<Option<Vec<ListEdit<String>>>, String>;
}

#[derive(Copy, Clone, Debug, Ord, PartialOrd, Eq, PartialEq)]
pub enum Source {
    Flag,
    Env,
    Config,
    Default,
}

#[derive(Debug)]
pub struct OptionValue<T> {
    pub source: Source,
    pub value: T,
}

impl<T> Deref for OptionValue<T> {
    type Target = T;

    fn deref(&self) -> &Self::Target {
        &self.value
    }
}

pub struct OptionParser {
    sources: BTreeMap<Source, Rc<dyn OptionsSource>>,
}

impl OptionParser {
    pub fn new() -> Result<OptionParser, String> {
        let mut sources: BTreeMap<Source, Rc<dyn OptionsSource>> = BTreeMap::new();
        sources.insert(Source::Env, Rc::new(Env::capture()));
        sources.insert(Source::Flag, Rc::new(Args::argv()));
        let mut parser = OptionParser {
            sources: sources.clone(),
        };

        let config_path = BuildRoot::find()?.join("pants.toml");
        let repo_config_files = parser.parse_string_list(
            &option_id!("pants", "config", "files"),
            &[
                std::str::from_utf8(config_path.as_os_str().as_bytes()).map_err(|e| {
                    format!(
                        "Failed to decode build root path {}: {}",
                        config_path.display(),
                        e
                    )
                })?,
            ],
        )?;
        let mut config = Config::merged(&repo_config_files)?;
        sources.insert(Source::Config, Rc::new(config.clone()));
        parser = OptionParser {
            sources: sources.clone(),
        };

        if *parser.parse_bool(&option_id!("pantsrc"), true)? {
            for rcfile in parser.parse_string_list(
                &option_id!("pantsrc", "files"),
                &["/etc/pantsrc", shellexpand::tilde("~/.pants.rc").as_ref()],
            )? {
                let rcfile_path = Path::new(&rcfile);
                if rcfile_path.exists() {
                    let rc_config = Config::parse(rcfile_path)?;
                    config = config.merge(rc_config);
                }
            }
        }
        sources.insert(Source::Config, Rc::new(config));
        Ok(OptionParser { sources })
    }

    pub fn parse_bool(&self, id: &OptionId, default: bool) -> Result<OptionValue<bool>, String> {
        for (source_type, source) in self.sources.iter() {
            if let Some(value) = source.get_bool(id)? {
                return Ok(OptionValue {
                    source: *source_type,
                    value,
                });
            }
        }
        Ok(OptionValue {
            source: Source::Default,
            value: default,
        })
    }

    pub fn parse_float(&self, id: &OptionId, default: f64) -> Result<OptionValue<f64>, String> {
        for (source_type, source) in self.sources.iter() {
            if let Some(value) = source.get_float(id)? {
                return Ok(OptionValue {
                    source: *source_type,
                    value,
                });
            }
        }
        Ok(OptionValue {
            source: Source::Default,
            value: default,
        })
    }

    pub fn parse_string(
        &self,
        id: &OptionId,
        default: &str,
    ) -> Result<OptionValue<String>, String> {
        for (source_type, source) in self.sources.iter() {
            if let Some(value) = source.get_string(id)? {
                return Ok(OptionValue {
                    source: *source_type,
                    value,
                });
            }
        }
        Ok(OptionValue {
            source: Source::Default,
            value: default.to_string(),
        })
    }

    pub fn parse_string_list(
        &self,
        id: &OptionId,
        default: &[&str],
    ) -> Result<Vec<String>, String> {
        let mut list_edits = vec![];
        for (_, source) in self.sources.iter() {
            if let Some(edits) = source.get_string_list(id)? {
                list_edits.extend(edits);
            }
        }
        let mut string_list = default.iter().map(|s| s.to_string()).collect::<Vec<_>>();
        for list_edit in list_edits {
            match list_edit.action {
                ListEditAction::Replace => string_list = list_edit.items,
                ListEditAction::Add => string_list.extend(list_edit.items),
                ListEditAction::Remove => {
                    let to_remove = list_edit.items.iter().collect::<HashSet<_>>();
                    string_list = string_list
                        .iter()
                        .filter(|item| !to_remove.contains(item))
                        .map(|s| s.to_owned())
                        .collect::<Vec<String>>();
                }
            }
        }
        Ok(string_list)
    }
}

pub fn render_choice(items: &[&str]) -> Option<String> {
    match items {
        [] => None,
        [this] => Some(this.to_string()),
        [this, that] => Some(format!("{this} or {that}")),
        [these @ .., that] => Some(format!("{} or {}", these.join(", "), that)),
    }
}
