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

use std::collections::{BTreeMap, HashMap, HashSet};
use std::hash::Hash;
use std::ops::Deref;
use std::os::unix::ffi::OsStrExt;
use std::path::Path;
use std::sync::Arc;

pub use self::args::Args;
use self::config::Config;
pub use self::env::Env;
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
/// The result of parsing a string-keyed dict, which may either be a Python dict literal represented
/// as a string, or a pre-parsed native dict.
///
/// The Literal format for a dict uses Python syntax, and so the only valid parser currently is
/// one provided by Python.
/// TODO: Implement a native parser for Python dict literals.
///
enum StringDict {
  Literal(String),
  Native(HashMap<String, toml::Value>),
}

///
/// A source of option values.
///
/// This is currently a subset of the types of options the Pants python option system handles.
/// Implementations should mimic the behavior of the equivalent python source.
///
pub(crate) trait OptionsSource: Send + Sync {
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
  /// Get the int option identified by `id` from this source.
  /// Errors when this source has an option value for `id` but that value is not a int.
  ///
  /// The default implementation looks for a string value for `id` and then attempts to parse it as
  /// a int value.
  ///
  fn get_int(&self, id: &OptionId) -> Result<Option<i64>, String> {
    if let Some(value) = self.get_string(id)? {
      value.parse().map(Some).map_err(|e| {
        format!(
          "Problem parsing {} value {} as an int value: {}",
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

  ///
  /// Get the string dict option identified by `id` from this source.
  /// Errors when this source has an option value for `id` but that value is not a string dict.
  ///
  /// The default implementation looks for a string Literal value for `id`.
  ///
  fn get_string_dict(&self, id: &OptionId) -> Result<Option<StringDict>, String> {
    if let Some(value) = self.get_string(id)? {
      Ok(Some(StringDict::Literal(value)))
    } else {
      Ok(None)
    }
  }
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
  sources: BTreeMap<Source, Arc<dyn OptionsSource>>,
}

impl OptionParser {
  pub fn new(env: Env, args: Args) -> Result<Self, String> {
    let mut sources: BTreeMap<Source, Arc<dyn OptionsSource>> = BTreeMap::new();
    sources.insert(Source::Env, Arc::new(env));
    sources.insert(Source::Flag, Arc::new(args));
    let mut parser = OptionParser {
      sources: sources.clone(),
    };

    let config_path = BuildRoot::find()?.join("pants.toml");
    let repo_config_files = parser
      .parse_string_list(
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
      )?
      .value;
    let mut config = Config::merged(&repo_config_files)?;
    sources.insert(Source::Config, Arc::new(config.clone()));
    parser = OptionParser {
      sources: sources.clone(),
    };

    if *parser.parse_bool(&option_id!("pantsrc"), true)? {
      for rcfile in parser
        .parse_string_list(
          &option_id!("pantsrc", "files"),
          &["/etc/pantsrc", shellexpand::tilde("~/.pants.rc").as_ref()],
        )?
        .value
      {
        let rcfile_path = Path::new(&rcfile);
        if rcfile_path.exists() {
          let rc_config = Config::parse(rcfile_path)?;
          config = config.merge(rc_config);
        }
      }
    }
    sources.insert(Source::Config, Arc::new(config));
    Ok(OptionParser { sources })
  }

  pub fn from_globals() -> Result<Self, String> {
    Self::new(Env::capture(), Args::argv())
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

  pub fn parse_int(&self, id: &OptionId, default: i64) -> Result<OptionValue<i64>, String> {
    for (source_type, source) in self.sources.iter() {
      if let Some(value) = source.get_int(id)? {
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

  pub fn parse_string(&self, id: &OptionId, default: &str) -> Result<OptionValue<String>, String> {
    self.parse_from_string(id, default, |s| Ok(s))
  }

  pub fn parse_from_string<T, D, P>(
    &self,
    id: &OptionId,
    default: D,
    parser: P,
  ) -> Result<OptionValue<T>, String>
  where
    T: From<D>,
    P: Fn(String) -> Result<T, String>,
  {
    for (source_type, source) in self.sources.iter() {
      if let Some(value) = source.get_string(id)? {
        return Ok(OptionValue {
          source: *source_type,
          value: parser(value)?,
        });
      }
    }
    Ok(OptionValue {
      source: Source::Default,
      value: default.into(),
    })
  }

  pub fn parse_string_list(
    &self,
    id: &OptionId,
    default: &[&str],
  ) -> Result<OptionValue<Vec<String>>, String> {
    self.parse_from_string_list(id, default, |s| Ok(s))
  }

  pub fn parse_from_string_list<T, D, P>(
    &self,
    id: &OptionId,
    default: &[D],
    parser: P,
  ) -> Result<OptionValue<Vec<T>>, String>
  where
    T: Hash + Eq + From<D>,
    D: Clone,
    P: Fn(String) -> Result<T, String>,
  {
    let mut list_edits = vec![];
    let mut last_source = Source::Default;
    for (source_type, source) in self.sources.iter() {
      if let Some(edits) = source.get_string_list(id)? {
        list_edits.extend(edits.into_iter().map(|e| (source, e)));
        // NB: We return the last encountered Source as the only Source. Although this is not
        // entirely accurate, it allows for consistency of the API.
        last_source = *source_type;
      }
    }
    let mut string_list: Vec<T> = default.into_iter().map(|s| s.clone().into()).collect();
    for (source, list_edit) in list_edits {
      let items = list_edit
        .items
        .into_iter()
        .map(|s| parser(s))
        .collect::<Result<Vec<T>, _>>()
        .map_err(|e| format!("Failed to parse {}: {}", source.display(id), e))?;
      match list_edit.action {
        ListEditAction::Replace => {
          string_list = items;
        }
        ListEditAction::Add => string_list.extend(items),
        ListEditAction::Remove => {
          let to_remove = items.into_iter().collect::<HashSet<T>>();
          string_list = string_list
            .into_iter()
            .filter(|item| !to_remove.contains(item))
            .collect::<Vec<T>>();
        }
      }
    }
    Ok(OptionValue {
      source: last_source,
      value: string_list,
    })
  }

  /// Parses a dict from either an embedded dict literal (in which case a Python parser for the
  /// entire value is necessary), or a native TOML dict (in which case only a per-value parser is
  /// necessary).
  pub fn parse_from_string_dict<T, D, MP, P>(
    &self,
    id: &OptionId,
    default: &HashMap<String, D>,
    member_parser: MP,
    literal_parser: P,
  ) -> Result<OptionValue<HashMap<String, T>>, String>
  where
    T: From<D>,
    D: Clone,
    MP: Fn(toml::Value) -> Result<T, String>,
    P: Fn(&str) -> Result<HashMap<String, T>, String>,
  {
    for (source_type, source) in self.sources.iter() {
      let value: HashMap<String, T> = match source.get_string_dict(id)? {
        Some(StringDict::Literal(literal)) => literal_parser(&literal)?,
        Some(StringDict::Native(dict)) => dict
          .into_iter()
          .map(|(k, v)| Ok((k, member_parser(v)?)))
          .collect::<Result<HashMap<String, T>, String>>()?,
        None => continue,
      };
      return Ok(OptionValue {
        source: *source_type,
        value,
      });
    }
    Ok(OptionValue {
      source: Source::Default,
      value: default
        .into_iter()
        .map(|(k, v)| {
          let v: T = v.clone().into();
          (k.clone(), v)
        })
        .collect(),
    })
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
