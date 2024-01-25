// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

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

#[cfg(test)]
mod tests;

mod types;

use std::collections::{BTreeMap, HashMap, HashSet};
use std::fmt::Debug;
use std::hash::Hash;
use std::ops::Deref;
use std::os::unix::ffi::OsStrExt;
use std::path;
use std::path::Path;
use std::rc::Rc;

pub use self::args::Args;
use self::config::Config;
pub use self::env::Env;
use crate::parse::{parse_float, parse_int};
pub use build_root::BuildRoot;
pub use id::{OptionId, Scope};
pub use types::OptionType;

// NB: The legacy Python options parser supported dicts with member_type "Any", which means
// the values can be arbitrarily-nested lists, tuples and dicts, including heterogeneous
// ones that are not supported as top-level option values. We have very few dict[Any] options,
// but there are a handful, and user plugins may also define them. Therefore we must continue
// to support this in the Rust options parser, hence this clunky enum.
//
// We only use this for parsing values in dicts, as in other cases we know that the type must
// be some scalar or string, or a uniform list of one type of scalar or string, so we can
// parse as such.
#[derive(Debug, PartialEq)]
pub enum Val {
    Bool(bool),
    Int(i64),
    Float(f64),
    String(String),
    List(Vec<Val>),
    Dict(HashMap<String, Val>),
}

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

#[derive(Copy, Clone, Debug, Eq, PartialEq)]
pub(crate) enum DictEditAction {
    Replace,
    Add,
}

#[derive(Debug, PartialEq)]
pub(crate) struct DictEdit {
    pub action: DictEditAction,
    pub items: HashMap<String, Val>,
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
    /// Get the int option identified by `id` from this source.
    /// Errors when this source has an option value for `id` but that value is not an int.
    ///
    /// The default implementation looks for a string value for `id` and then attempts to parse it as
    /// an int value.
    ///
    fn get_int(&self, id: &OptionId) -> Result<Option<i64>, String> {
        if let Some(value) = self.get_string(id)? {
            parse_int(&value)
                .map(Some)
                .map_err(|e| e.render(self.display(id)))
        } else {
            Ok(None)
        }
    }

    ///
    /// Get the float option identified by `id` from this source.
    /// Errors when this source has an option value for `id` but that value is not a float or an int
    /// that we can coerce to a float.
    ///
    /// The default implementation looks for a string value for `id` and then attempts to parse it as
    /// a float value.
    ///
    fn get_float(&self, id: &OptionId) -> Result<Option<f64>, String> {
        if let Some(value) = self.get_string(id)? {
            let parsed_as_float = parse_float(&value)
                .map(Some)
                .map_err(|e| e.render(self.display(id)));
            if parsed_as_float.is_err() {
                // See if we can parse as an int and coerce it to a float.
                if let Ok(i) = parse_int(&value) {
                    return Ok(Some(i as f64));
                }
            }
            parsed_as_float
        } else {
            Ok(None)
        }
    }

    ///
    /// Get the bool list option identified by `id` from this source.
    /// Errors when this source has an option value for `id` but that value is not a bool list.
    ///
    fn get_bool_list(&self, id: &OptionId) -> Result<Option<Vec<ListEdit<bool>>>, String>;

    ///
    /// Get the int list option identified by `id` from this source.
    /// Errors when this source has an option value for `id` but that value is not an int list.
    ///
    fn get_int_list(&self, id: &OptionId) -> Result<Option<Vec<ListEdit<i64>>>, String>;

    ///
    /// Get the float list option identified by `id` from this source.
    /// Errors when this source has an option value for `id` but that value is not a float list.
    ///
    fn get_float_list(&self, id: &OptionId) -> Result<Option<Vec<ListEdit<f64>>>, String>;

    ///
    /// Get the string list option identified by `id` from this source.
    /// Errors when this source has an option value for `id` but that value is not a string list.
    ///
    fn get_string_list(&self, id: &OptionId) -> Result<Option<Vec<ListEdit<String>>>, String>;

    ///
    /// Get the dict option identified by `id` from this source.
    /// Errors when this source has an option value for `id` but that value is not a dict.
    ///
    fn get_dict(&self, id: &OptionId) -> Result<Option<Vec<DictEdit>>, String>;
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
    // If config_paths is None, we'll do config file discovery. Otherwise we'll use the provided paths.
    // The latter case is useful for tests.
    pub fn new(
        args: Args,
        env: Env,
        config_paths: Option<Vec<&str>>,
        allow_pantsrc: bool,
    ) -> Result<OptionParser, String> {
        let buildroot = BuildRoot::find()?;
        let buildroot_string = String::from_utf8(buildroot.as_os_str().as_bytes().to_vec())
            .map_err(|e| {
                format!(
                    "Failed to decode build root path {}: {}",
                    buildroot.display(),
                    e
                )
            })?;

        let mut seed_values = HashMap::from_iter(
            env.env
                .iter()
                .map(|(k, v)| (format!("env.{k}", k = k), v.clone())),
        );

        let mut sources: BTreeMap<Source, Rc<dyn OptionsSource>> = BTreeMap::new();
        sources.insert(Source::Env, Rc::new(env));
        sources.insert(Source::Flag, Rc::new(args));
        let mut parser = OptionParser {
            sources: sources.clone(),
        };

        fn path_join(a: &str, b: &str) -> String {
            format!("{}{}{}", a, path::MAIN_SEPARATOR, b)
        }

        let repo_config_files = match config_paths {
            Some(paths) => paths.iter().map(|s| s.to_string()).collect(),
            None => {
                let default_config_path = path_join(&buildroot_string, "pants.toml");
                parser.parse_string_list(
                    &option_id!("pants", "config", "files"),
                    &[&default_config_path],
                )?
            }
        };

        let subdir = |subdir_name: &str, default: &str| -> Result<String, String> {
            Ok(parser
                .parse_string(
                    &OptionId::new(Scope::Global, ["pants", subdir_name].iter(), None)?,
                    &path_join(&buildroot_string, default),
                )?
                .value
                .clone())
        };

        seed_values.extend([
            ("buildroot".to_string(), buildroot_string.clone()),
            ("homedir".to_string(), shellexpand::tilde("~").into_owned()),
            ("user".to_string(), whoami::username()),
            ("pants_workdir".to_string(), subdir("workdir", ".pants.d")?),
            ("pants_distdir".to_string(), subdir("distdir", "dist")?),
        ]);

        let mut config = Config::parse(&repo_config_files, &seed_values)?;
        sources.insert(Source::Config, Rc::new(config.clone()));
        parser = OptionParser {
            sources: sources.clone(),
        };

        if allow_pantsrc && *parser.parse_bool(&option_id!("pantsrc"), true)? {
            for rcfile in parser.parse_string_list(
                &option_id!("pantsrc", "files"),
                &[
                    "/etc/pantsrc",
                    shellexpand::tilde("~/.pants.rc").as_ref(),
                    ".pants.rc",
                ],
            )? {
                let rcfile_path = Path::new(&rcfile);
                if rcfile_path.exists() {
                    let rc_config = Config::parse(&[rcfile_path], &seed_values)?;
                    config = config.merge(rc_config);
                }
            }
        }
        sources.insert(Source::Config, Rc::new(config));
        Ok(OptionParser { sources })
    }

    #[allow(clippy::type_complexity)]
    fn parse_scalar<T: ToOwned + ?Sized>(
        &self,
        id: &OptionId,
        default: &T,
        getter: fn(&Rc<dyn OptionsSource>, &OptionId) -> Result<Option<T::Owned>, String>,
    ) -> Result<OptionValue<T::Owned>, String> {
        for (source_type, source) in self.sources.iter() {
            if let Some(value) = getter(source, id)? {
                return Ok(OptionValue {
                    source: *source_type,
                    value,
                });
            }
        }
        Ok(OptionValue {
            source: Source::Default,
            value: default.to_owned(),
        })
    }

    pub fn parse_bool(&self, id: &OptionId, default: bool) -> Result<OptionValue<bool>, String> {
        self.parse_scalar(id, &default, |source, id| source.get_bool(id))
    }

    pub fn parse_int(&self, id: &OptionId, default: i64) -> Result<OptionValue<i64>, String> {
        self.parse_scalar(id, &default, |source, id| source.get_int(id))
    }

    pub fn parse_float(&self, id: &OptionId, default: f64) -> Result<OptionValue<f64>, String> {
        self.parse_scalar(id, &default, |source, id| source.get_float(id))
    }

    pub fn parse_string(
        &self,
        id: &OptionId,
        default: &str,
    ) -> Result<OptionValue<String>, String> {
        self.parse_scalar(id, default, |source, id| source.get_string(id))
    }

    #[allow(clippy::type_complexity)]
    fn parse_list<T>(
        &self,
        id: &OptionId,
        default: Vec<T>,
        getter: fn(&Rc<dyn OptionsSource>, &OptionId) -> Result<Option<Vec<ListEdit<T>>>, String>,
        remover: fn(&mut Vec<T>, &Vec<T>),
    ) -> Result<Vec<T>, String> {
        let mut list = default;
        for (_source_type, source) in self.sources.iter().rev() {
            if let Some(list_edits) = getter(source, id)? {
                for list_edit in list_edits {
                    match list_edit.action {
                        ListEditAction::Replace => list = list_edit.items,
                        ListEditAction::Add => list.extend(list_edit.items),
                        ListEditAction::Remove => remover(&mut list, &list_edit.items),
                    }
                }
            }
        }
        Ok(list)
    }

    // For Eq+Hash types we can use a HashSet when computing removals, which will be avg O(N+M).
    // In practice it's likely that constructing the hash set for a tiny number of is actually
    // slower than doing this with O(N*M) brute-force lookups, since we expect the size of the
    // removal set to be tiny in almost any case.
    // However this is still more than fast enough, and inoculates us against a very unlikely
    // pathological case of a very large removal set.
    #[allow(clippy::type_complexity)]
    fn parse_list_hashable<T: Eq + Hash>(
        &self,
        id: &OptionId,
        default: Vec<T>,
        getter: fn(&Rc<dyn OptionsSource>, &OptionId) -> Result<Option<Vec<ListEdit<T>>>, String>,
    ) -> Result<Vec<T>, String> {
        self.parse_list(id, default, getter, |list, remove| {
            let to_remove = remove.iter().collect::<HashSet<_>>();
            list.retain(|item| !to_remove.contains(item));
        })
    }

    pub fn parse_bool_list(&self, id: &OptionId, default: &[bool]) -> Result<Vec<bool>, String> {
        self.parse_list_hashable(id, default.to_vec(), |source, id| source.get_bool_list(id))
    }

    pub fn parse_int_list(&self, id: &OptionId, default: &[i64]) -> Result<Vec<i64>, String> {
        self.parse_list_hashable(id, default.to_vec(), |source, id| source.get_int_list(id))
    }

    // Floats are not Eq or Hash, so we fall back to the brute-force O(N*M) lookups.
    pub fn parse_float_list(&self, id: &OptionId, default: &[f64]) -> Result<Vec<f64>, String> {
        self.parse_list(
            id,
            default.to_vec(),
            |source, id| source.get_float_list(id),
            |list, to_remove| {
                list.retain(|item| !to_remove.contains(item));
            },
        )
    }

    pub fn parse_string_list(
        &self,
        id: &OptionId,
        default: &[&str],
    ) -> Result<Vec<String>, String> {
        self.parse_list_hashable::<String>(
            id,
            default.iter().map(|s| s.to_string()).collect(),
            |source, id| source.get_string_list(id),
        )
    }

    pub fn parse_dict(
        &self,
        id: &OptionId,
        default: HashMap<String, Val>,
    ) -> Result<HashMap<String, Val>, String> {
        let mut dict = default;
        for (_, source) in self.sources.iter().rev() {
            if let Some(dict_edit) = source.get_dict(id)? {
                match dict_edit.action {
                    DictEditAction::Replace => dict = dict_edit.items,
                    DictEditAction::Add => dict.extend(dict_edit.items),
                }
            }
        }
        Ok(dict)
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
