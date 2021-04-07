// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

mod args;
mod config;
mod env;
mod id;
mod parse;

use std::collections::{BTreeMap, HashSet};
use std::ops::Deref;
use std::os::unix::ffi::OsStrExt;
use std::path::Path;
use std::rc::Rc;

use crate::build_root::BuildRoot;
use crate::option_id;

use args::Args;
use config::Config;
use env::Env;
use parse::{parse_bool, parse_string_list};

pub use id::{OptionId, Scope};

#[derive(Copy, Clone, Debug)]
pub(crate) enum ListEditAction {
  REPLACE,
  ADD,
  REMOVE,
}

#[derive(Debug)]
pub(crate) struct ListEdit<T> {
  pub action: ListEditAction,
  pub items: Vec<T>,
}

trait OptionsSource {
  fn display(&self, id: &OptionId) -> String {
    format!("{}", id)
  }

  fn get_string(&self, id: &OptionId) -> Result<Option<String>, String>;

  fn get_bool(&self, id: &OptionId) -> Result<Option<bool>, String> {
    if let Some(value) = self.get_string(id)? {
      parse_bool(&*self.display(id), &*value).map(Some)
    } else {
      Ok(None)
    }
  }

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

  fn get_string_list(&self, id: &OptionId) -> Result<Option<Vec<ListEdit<String>>>, String> {
    if let Some(value) = self.get_string(id)? {
      parse_string_list(&*self.display(id), &value).map(Some)
    } else {
      Ok(None)
    }
  }
}

#[derive(Copy, Clone, Debug, Ord, PartialOrd, Eq, PartialEq)]
pub enum Source {
  FLAG,
  ENV,
  CONFIG,
  DEFAULT,
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
    sources.insert(Source::ENV, Rc::new(Env::capture()));
    sources.insert(Source::FLAG, Rc::new(Args::argv()));
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
    sources.insert(Source::CONFIG, Rc::new(config.clone()));
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
    sources.insert(Source::CONFIG, Rc::new(config));
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
      source: Source::DEFAULT,
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
      source: Source::DEFAULT,
      value: default,
    })
  }

  pub fn parse_string(&self, id: &OptionId, default: &str) -> Result<OptionValue<String>, String> {
    for (source_type, source) in self.sources.iter() {
      if let Some(value) = source.get_string(id)? {
        return Ok(OptionValue {
          source: *source_type,
          value,
        });
      }
    }
    Ok(OptionValue {
      source: Source::DEFAULT,
      value: default.to_string(),
    })
  }

  pub fn parse_string_list(&self, id: &OptionId, default: &[&str]) -> Result<Vec<String>, String> {
    let mut list_edits = vec![];
    for (_, source) in self.sources.iter() {
      if let Some(edits) = source.get_string_list(id)? {
        for edit in edits {
          list_edits.push(edit);
        }
      }
    }
    let mut string_list = default.iter().map(|s| s.to_string()).collect::<Vec<_>>();
    for list_edit in list_edits {
      match list_edit.action {
        ListEditAction::REPLACE => string_list = list_edit.items,
        ListEditAction::ADD => {
          for item in list_edit.items {
            string_list.push(item);
          }
        }
        ListEditAction::REMOVE => {
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
