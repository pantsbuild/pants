// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

pub mod arg_splitter;
#[cfg(test)]
mod arg_splitter_tests;

mod flags;
#[cfg(test)]
mod flags_tests;

mod build_root;
#[cfg(test)]
mod build_root_tests;

pub mod config;
#[cfg(test)]
mod config_tests;

mod cli_alias;
#[cfg(test)]
mod cli_alias_tests;

pub mod env;
#[cfg(test)]
mod env_tests;

pub mod fromfile;
#[cfg(test)]
mod fromfile_tests;

mod id;
#[cfg(test)]
mod id_tests;

pub mod pants_ng_flags;
#[cfg(test)]
pub mod pants_ng_flags_tests;

mod parse;
#[cfg(test)]
mod parse_tests;

mod scope;

#[cfg(test)]
mod tests;

mod types;

use self::arg_splitter::ArgSplitter;
pub use self::arg_splitter::{Args, PantsCommand};
pub use self::config::ConfigSource;
use self::config::{Config, ConfigReader};
pub use self::env::Env;
use self::env::EnvReader;
use self::flags::FlagsReader;
use crate::cli_alias::expand_aliases;
use crate::fromfile::FromfileExpander;
use crate::parse::Parseable;
pub use build_root::BuildRoot;
pub use id::OptionId;
use parking_lot::Mutex;
pub use scope::{GoalInfo, Scope};
use serde::Deserialize;
use std::any::Any;
use std::collections::{BTreeMap, HashMap, HashSet};
use std::fmt::Debug;
use std::fs;
use std::hash::Hash;
use std::path::Path;
use std::sync::Arc;
use std::sync::LazyLock;
pub use types::OptionType;

static BIN_NAME: LazyLock<Mutex<String>> = LazyLock::new(|| Mutex::new("pants".to_string()));

// NB: This will be called at import time in several Python files to define static help strings
// (e.g. "help=f'run `{bin_name()} fmt`"). So it must be set early. But on the other hand it can
// only be set after we parse options and have access to the pants_bin_name option, which may
// be too late: Some of the files that register options may already be using `bin_name()`.
//
// Fortunately, this only applies in pantsd; The native client does not have this problem because
// it parses options without registration. So we use the __PANTS_BIN_NAME env var to propagate
// this value from the native client to its spawned pantsd process (see pants_daemon_client.py).
pub fn bin_name() -> String {
    if let Ok(bin_name) = std::env::var("__PANTS_BIN_NAME") {
        bin_name
    } else {
        BIN_NAME.lock().clone()
    }
}

fn munge_bin_name(pants_bin_name: String, build_root: &BuildRoot) -> String {
    // Determine a useful bin name to embed in help strings.
    // The bin name gets embedded in help comments in generated lockfiles,
    // so we never want to use an abspath.
    let pants_bin = Path::new(&pants_bin_name);
    if pants_bin.is_absolute() {
        if let Ok(suffix) = pants_bin.strip_prefix(build_root.as_path()) {
            return Path::new(".").join(suffix).to_string_lossy().to_string();
        }
        return pants_bin
            .file_name()
            .map(|osstr| osstr.to_string_lossy().to_string())
            .unwrap_or("pants".to_string());
    }
    pants_bin_name
}

// NB: The legacy Python options parser supported dicts with member_type "Any", which means
// the values can be arbitrarily-nested lists, tuples and dicts, including heterogeneous
// ones that are not supported as top-level option values. We have very few dict[Any] options,
// but there are a handful, and user plugins may also define them. Therefore we must continue
// to support this in the Rust options parser, hence this clunky enum.
//
// We only use this for parsing values in dicts, as in other cases we know that the type must
// be some scalar or string, or a uniform list of one type of scalar or string, so we can
// parse as such.
#[derive(Clone, Debug, PartialEq, Deserialize)]
#[serde(untagged)]
pub enum Val {
    Bool(bool),
    Int(i64),
    Float(f64),
    String(String),
    List(Vec<Val>),
    Dict(HashMap<String, Val>),
}

#[derive(Copy, Clone, Debug, Eq, PartialEq)]
pub enum ListEditAction {
    Replace,
    Add,
    Remove,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ListEdit<T> {
    pub action: ListEditAction,
    pub items: Vec<T>,
}

#[derive(Copy, Clone, Debug, Eq, PartialEq)]
pub enum DictEditAction {
    Replace,
    Add,
}

#[derive(Clone, Debug, PartialEq)]
pub struct DictEdit {
    pub action: DictEditAction,
    pub items: HashMap<String, Val>,
}

pub trait OptionsSource: Send + Sync {
    ///
    /// Get a display version of the option `id` that most closely matches the syntax used to supply
    /// the id at runtime. For example, an global option of "bob" would display as "--bob" for use in
    /// flag based options and "BOB" in environment variable based options.
    ///
    fn display(&self, id: &OptionId) -> String;

    fn as_any(&self) -> &dyn Any;

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
            i64::parse(&value)
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
            let parsed_as_float = f64::parse(&value)
                .map(Some)
                .map_err(|e| e.render(self.display(id)));
            if parsed_as_float.is_err() {
                // See if we can parse as an int and coerce it to a float.
                if let Ok(i) = i64::parse(&value) {
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

#[derive(Clone, Debug, Ord, PartialOrd, Eq, Hash, PartialEq)]
pub enum Source {
    Default,
    Config { ordinal: usize, path: String }, // TODO: Should be a PathBuf
    Env,
    Flag,
}

// NB: Must mirror the Rank enum in src/python/pants/option/ranked_value.py.
pub enum Rank {
    _NONE = 0,          // Unused, exists for historical Python compatibility reasons.
    HARDCODED = 1,      // The default provided at option registration.
    _CONFIGDEFAULT = 2, // Unused, exists for historical Python compatibility reasons.
    CONFIG = 3,         // The value from the relevant section of the config file.
    ENVIRONMENT = 4,    // The value from the appropriately-named environment variable.
    FLAG = 5,           // The value from the appropriately-named command-line flag.
}

impl Source {
    pub fn rank(&self) -> Rank {
        match *self {
            Source::Default => Rank::HARDCODED,
            Source::Config {
                ordinal: _,
                path: _,
            } => Rank::CONFIG,
            Source::Env => Rank::ENVIRONMENT,
            Source::Flag => Rank::FLAG,
        }
    }
}

pub fn apply_list_edits<T>(
    remover: fn(&mut Vec<T>, &[T]),
    list_edits: impl Iterator<Item = ListEdit<T>>,
) -> Vec<T> {
    let mut list = vec![];
    // Removals from any source apply after adds from any source (but are themselves
    // overridden by later replacements), so we collect them here and apply them later.
    let mut removal_lists: Vec<Vec<T>> = vec![];

    for list_edit in list_edits {
        match list_edit.action {
            ListEditAction::Replace => {
                list = list_edit.items;
                removal_lists.clear();
            }
            ListEditAction::Add => list.extend(list_edit.items),
            ListEditAction::Remove => removal_lists.push(list_edit.items),
        }
    }

    for removals in removal_lists {
        remover(&mut list, &removals);
    }

    list
}

pub fn apply_dict_edits(dict_edits: impl Iterator<Item = DictEdit>) -> HashMap<String, Val> {
    let mut dict = HashMap::new();
    for dict_edit in dict_edits {
        match dict_edit.action {
            DictEditAction::Replace => dict = dict_edit.items,
            DictEditAction::Add => dict.extend(dict_edit.items),
        }
    }
    dict
}

#[derive(Debug)]
pub struct OptionValue<'a, T> {
    pub derivation: Option<Vec<(&'a Source, T)>>,
    pub source: &'a Source,
    pub value: T,
}

#[derive(Debug)]
pub struct OptionalOptionValue<'a, T> {
    pub derivation: Option<Vec<(&'a Source, T)>>,
    pub source: &'a Source,
    pub value: Option<T>,
}

impl<'a, T> OptionalOptionValue<'a, T> {
    fn unwrap(self) -> OptionValue<'a, T> {
        OptionValue {
            derivation: self.derivation,
            source: self.source,
            value: self.value.unwrap(),
        }
    }
}

#[derive(Debug)]
pub struct ListOptionValue<'a, T> {
    #[allow(clippy::type_complexity)]
    pub derivation: Option<Vec<(&'a Source, Vec<ListEdit<T>>)>>,
    // The highest-priority source that provided edits for this value.
    pub source: &'a Source,
    pub value: Vec<T>,
}

#[derive(Debug)]
pub struct DictOptionValue<'a> {
    pub derivation: Option<Vec<(&'a Source, Vec<DictEdit>)>>,
    // The highest-priority source that provided edits for this value.
    pub source: &'a Source,
    pub value: HashMap<String, Val>,
}

pub struct OptionParser {
    sources: BTreeMap<Source, Arc<dyn OptionsSource>>,
    include_derivation: bool,
    pub command: PantsCommand,
}

impl OptionParser {
    // If config_sources is None, we'll do config file discovery. Otherwise we'll use the
    // provided sources. The latter case is useful for tests.
    pub fn new(
        args: Args,
        env: Env,
        config_sources: Option<Vec<ConfigSource>>,
        allow_pantsrc: bool,
        include_derivation: bool,
        buildroot: Option<BuildRoot>,
        // TODO: pass the raw option registration data in instead, so that a single
        //  arg can serve instead of these two args, and can also be used for
        //  validating config files.
        //  For now this is just what we need to validate CLI aliases and
        //  detect goals.
        known_scopes_to_flags: Option<&HashMap<String, HashSet<String>>>,
        known_goals: Option<Vec<GoalInfo>>,
    ) -> Result<OptionParser, String> {
        let has_provided_configs = config_sources.is_some();

        let buildroot = match buildroot {
            Some(buildroot) => buildroot,
            None => BuildRoot::find()?,
        };
        let buildroot_string = buildroot.convert_to_string()?;

        let mut sources: BTreeMap<Source, Arc<dyn OptionsSource>> = BTreeMap::new();

        let arg_splitter = ArgSplitter::new(buildroot.as_path(), known_goals.unwrap_or_default());
        let fromfile_expander = FromfileExpander::relative_to(buildroot.clone());

        let mut seed_values =
            BTreeMap::from_iter(env.env.iter().map(|(k, v)| (format!("env.{k}"), v.clone())));

        // We bootstrap options in several steps.

        // Step #1: Read env and (non cli alias-expanded) args to find config files and
        // the workdir/distdir.

        sources.insert(
            Source::Env,
            Arc::new(EnvReader::new(env, fromfile_expander.clone())),
        );
        sources.insert(
            Source::Flag,
            Arc::new(FlagsReader::new(
                arg_splitter.split_args(args.clone()).flags,
                fromfile_expander.clone(),
            )),
        );
        let mut parser = OptionParser {
            sources: sources.clone(),
            include_derivation: false,
            command: PantsCommand::empty(),
        };

        fn path_join(prefix: &str, suffix: &str) -> String {
            // TODO: The calling code should traffic in Path, or OsString, not String.
            //  For now we assume the paths are valid UTF8 strings, via unwrap().
            Path::new(prefix).join(suffix).to_str().unwrap().to_string()
        }

        fn path_strip(prefix: &str, path: &str) -> String {
            // TODO: The calling code should traffic in Path, or OsString, not String.
            //  For now we assume the paths are valid UTF8 strings, via unwrap().
            let path = Path::new(path);
            path.strip_prefix(prefix)
                .unwrap_or(path)
                .to_str()
                .unwrap()
                .to_string()
        }

        let config_sources = match config_sources {
            Some(cs) => cs,
            None => {
                // If a pants.toml exists at the build root, use it as the default config file
                // if no config files were explicitly specified via --pants-config-files
                // (or PANTS_CONFIG_FILES).
                // If it doesn't exist, proceed with no config files. We don't need to error
                // if no config file exists (we may error later if an option value is not
                // provided).
                // In regular usage there is always a config file in practice, but there may not
                // be in some obscure test scenarios.
                let default_config_path = path_join(&buildroot_string, "pants.toml");
                let default_config_paths =
                    if fs::exists(Path::new(&default_config_path)).map_err(|e| e.to_string())? {
                        vec![default_config_path]
                    } else {
                        vec![]
                    };
                let config_paths = parser
                    .parse_string_list(
                        &option_id!("pants", "config", "files"),
                        default_config_paths,
                    )?
                    .value;
                config_paths
                    .iter()
                    .map(|cp| ConfigSource::from_file(Path::new(&cp)))
                    .collect::<Result<Vec<_>, _>>()?
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

        // Step #2: Read (unexpanded) args, env, and config to find rcfiles.

        let mut ordinal: usize = 0;
        for config_source in config_sources {
            let config = Config::parse(&config_source, &seed_values)?;
            sources.insert(
                Source::Config {
                    ordinal,
                    path: path_strip(
                        &buildroot_string,
                        config_source.path.to_string_lossy().as_ref(),
                    ),
                },
                Arc::new(ConfigReader::new(config, fromfile_expander.clone())),
            );
            ordinal += 1;
        }

        parser = OptionParser {
            sources: sources.clone(),
            include_derivation: false,
            command: PantsCommand::empty(),
        };

        if allow_pantsrc
            && parser.parse_bool(&option_id!("pantsrc"), true)?.value
            && !has_provided_configs
        {
            for rcfile in parser
                .parse_string_list(
                    &option_id!("pantsrc", "files"),
                    vec![
                        "/etc/pantsrc".to_string(),
                        shellexpand::tilde("~/.pants.rc").to_string(),
                        ".pants.rc".to_string(),
                    ],
                )?
                .value
            {
                let rcfile_path = Path::new(&rcfile);
                if rcfile_path.exists() {
                    let rc_config =
                        Config::parse(&ConfigSource::from_file(rcfile_path)?, &seed_values)?;
                    sources.insert(
                        Source::Config {
                            ordinal,
                            path: rcfile,
                        },
                        Arc::new(ConfigReader::new(rc_config, fromfile_expander.clone())),
                    );
                    ordinal += 1;
                }
            }
        }

        // Step #3: Read env and config (but not args) to find cli aliases.

        // Remove the args source, as we don't support providing cli aliases on the cli...
        sources.remove(&Source::Flag).unwrap();

        parser = OptionParser {
            sources: sources.clone(),
            include_derivation: false,
            command: PantsCommand::empty(),
        };
        let alias_strings = parser
            .parse_dict(&option_id!(["cli"], "alias"), HashMap::new())?
            .value
            .into_iter()
            .map(|(k, v)| {
                if let Val::String(s) = v {
                    Ok((k, s))
                } else {
                    Err(format!("Values in [cli.alias] must be strings. Got: {v:?}"))
                }
            })
            .collect::<Result<HashMap<_, _>, String>>()?;

        let alias_map = cli_alias::create_alias_map(known_scopes_to_flags, &alias_strings)?;

        // Step #4: Read any spec_files from alias-expanded flags, env, config and rcfiles.

        let expanded_args = Args::new(expand_aliases(args.arg_strings.clone(), &alias_map));
        // Now get the final PantsCommand based on the expanded aliases.
        let command = arg_splitter.split_args(expanded_args);
        sources.insert(
            Source::Flag,
            Arc::new(FlagsReader::new(
                command.flags.clone(),
                fromfile_expander.clone(),
            )),
        );

        parser = OptionParser {
            sources: sources.clone(),
            include_derivation,
            command,
        };

        // Apply the bin name set by the user, if any.
        if let Ok(val) = parser.parse_string_optional(&option_id!("pants", "bin", "name"), None)
            && let Some(bin_name) = val.value
        {
            *BIN_NAME.lock() = munge_bin_name(bin_name, &buildroot);
        }

        // Step #5: Return the final OptionParser, with any extra specs from spec_files added
        // to the command.

        let extra_specs = parser
            .parse_string_list(&option_id!("spec", "files"), vec![])?
            .value;
        if extra_specs.is_empty() {
            Ok(parser)
        } else {
            let mut extra_specs = vec![];
            for spec_file in parser
                .parse_string_list(&option_id!("spec", "files"), vec![])?
                .value
            {
                extra_specs.extend(
                    fs::read_to_string(buildroot.as_path().join(&spec_file))
                        .map_err(|e| e.to_string())?
                        .lines()
                        .filter(|s| !s.is_empty())
                        .map(str::to_string),
                );
            }
            Ok(OptionParser {
                sources,
                include_derivation,
                command: parser.command.add_specs(extra_specs),
            })
        }
    }

    // The pants_ng options code uses an old OptionParser for convenience,
    // but sets up the sources itself.
    pub fn new_pants_ng(
        sources: BTreeMap<Source, Arc<dyn OptionsSource>>,
        include_derivation: bool,
    ) -> Self {
        // pants_ng has its own type to represent a Pants command line, which is not
        // compatible with the old PantsCommand, so we set this to a dummy
        let dummy_command = PantsCommand::empty();
        Self {
            sources,
            include_derivation,
            command: dummy_command,
        }
    }

    #[allow(clippy::type_complexity)]
    fn parse_scalar<T: ToOwned + ?Sized>(
        &self,
        id: &OptionId,
        default: Option<&T>,
        getter: fn(&Arc<dyn OptionsSource>, &OptionId) -> Result<Option<T::Owned>, String>,
    ) -> Result<OptionalOptionValue<'_, T::Owned>, String> {
        let mut derivation = None;
        if self.include_derivation {
            let mut derivations = vec![];
            if let Some(def) = default {
                derivations.push((&Source::Default, def.to_owned()));
            }
            for (source_type, source) in self.sources.iter() {
                if let Some(val) = getter(source, id)? {
                    derivations.push((source_type, val));
                }
            }
            derivation = Some(derivations);
        }
        for (source_type, source) in self.sources.iter().rev() {
            if let Some(value) = getter(source, id)? {
                return Ok(OptionalOptionValue {
                    derivation,
                    source: source_type,
                    value: Some(value),
                });
            }
        }
        Ok(OptionalOptionValue {
            derivation,
            source: &Source::Default,
            value: default.map(|x| x.to_owned()),
        })
    }

    pub fn parse_bool_optional(
        &self,
        id: &OptionId,
        default: Option<bool>,
    ) -> Result<OptionalOptionValue<'_, bool>, String> {
        self.parse_scalar(id, default.as_ref(), |source, id| source.get_bool(id))
    }

    pub fn parse_int_optional(
        &self,
        id: &OptionId,
        default: Option<i64>,
    ) -> Result<OptionalOptionValue<'_, i64>, String> {
        self.parse_scalar(id, default.as_ref(), |source, id| source.get_int(id))
    }

    pub fn parse_float_optional(
        &self,
        id: &OptionId,
        default: Option<f64>,
    ) -> Result<OptionalOptionValue<'_, f64>, String> {
        self.parse_scalar(id, default.as_ref(), |source, id| source.get_float(id))
    }

    pub fn parse_string_optional(
        &self,
        id: &OptionId,
        default: Option<&str>,
    ) -> Result<OptionalOptionValue<'_, String>, String> {
        self.parse_scalar(id, default, |source, id| source.get_string(id))
    }

    pub fn parse_bool(
        &self,
        id: &OptionId,
        default: bool,
    ) -> Result<OptionValue<'_, bool>, String> {
        self.parse_bool_optional(id, Some(default))
            .map(OptionalOptionValue::unwrap)
    }

    pub fn parse_int(&self, id: &OptionId, default: i64) -> Result<OptionValue<'_, i64>, String> {
        self.parse_int_optional(id, Some(default))
            .map(OptionalOptionValue::unwrap)
    }

    pub fn parse_float(&self, id: &OptionId, default: f64) -> Result<OptionValue<'_, f64>, String> {
        self.parse_float_optional(id, Some(default))
            .map(OptionalOptionValue::unwrap)
    }

    pub fn parse_string(
        &self,
        id: &OptionId,
        default: &str,
    ) -> Result<OptionValue<'_, String>, String> {
        self.parse_string_optional(id, Some(default))
            .map(OptionalOptionValue::unwrap)
    }

    #[allow(clippy::type_complexity)]
    fn parse_list<T: Clone + Debug>(
        &self,
        id: &OptionId,
        default: Vec<T>,
        getter: fn(&Arc<dyn OptionsSource>, &OptionId) -> Result<Option<Vec<ListEdit<T>>>, String>,
        remover: fn(&mut Vec<T>, &[T]),
    ) -> Result<ListOptionValue<'_, T>, String> {
        let mut derivation = None;
        if self.include_derivation {
            let mut derivations = vec![(
                &Source::Default,
                vec![ListEdit {
                    action: ListEditAction::Replace,
                    items: default.clone(),
                }],
            )];
            for (source_type, source) in self.sources.iter() {
                if let Some(list_edits) = getter(source, id)?
                    && !list_edits.is_empty()
                {
                    derivations.push((source_type, list_edits));
                }
            }
            derivation = Some(derivations);
        }

        let mut highest_priority_source = &Source::Default;
        let mut edits: Vec<ListEdit<T>> = vec![ListEdit {
            action: ListEditAction::Replace,
            items: default,
        }];
        for (source_type, source) in self.sources.iter() {
            if let Some(list_edits) = getter(source, id)? {
                highest_priority_source = source_type;
                edits.extend(list_edits);
            }
        }

        Ok(ListOptionValue {
            derivation,
            source: highest_priority_source,
            value: apply_list_edits(remover, edits.into_iter()),
        })
    }

    // For Eq+Hash types we can use a HashSet when computing removals, which will be avg O(N+M).
    // In practice it's likely that constructing the hash set for a tiny number of is actually
    // slower than doing this with O(N*M) brute-force lookups, since we expect the size of the
    // removal set to be tiny in almost any case.
    // However this is still more than fast enough, and inoculates us against a very unlikely
    // pathological case of a very large removal set.
    #[allow(clippy::type_complexity)]
    fn parse_list_hashable<T: Clone + Debug + Eq + Hash>(
        &self,
        id: &OptionId,
        default: Vec<T>,
        getter: fn(&Arc<dyn OptionsSource>, &OptionId) -> Result<Option<Vec<ListEdit<T>>>, String>,
    ) -> Result<ListOptionValue<'_, T>, String> {
        self.parse_list(id, default, getter, |list, remove| {
            let to_remove = remove.iter().collect::<HashSet<_>>();
            list.retain(|item| !to_remove.contains(item));
        })
    }

    pub fn parse_bool_list(
        &self,
        id: &OptionId,
        default: Vec<bool>,
    ) -> Result<ListOptionValue<'_, bool>, String> {
        self.parse_list_hashable(id, default, |source, id| source.get_bool_list(id))
    }

    pub fn parse_int_list(
        &self,
        id: &OptionId,
        default: Vec<i64>,
    ) -> Result<ListOptionValue<'_, i64>, String> {
        self.parse_list_hashable(id, default, |source, id| source.get_int_list(id))
    }

    // Floats are not Eq or Hash, so we fall back to the brute-force O(N*M) lookups.
    pub fn parse_float_list(
        &self,
        id: &OptionId,
        default: Vec<f64>,
    ) -> Result<ListOptionValue<'_, f64>, String> {
        self.parse_list(
            id,
            default,
            |source, id| source.get_float_list(id),
            |list, to_remove| {
                list.retain(|item| !to_remove.contains(item));
            },
        )
    }

    pub fn parse_string_list(
        &self,
        id: &OptionId,
        default: Vec<String>,
    ) -> Result<ListOptionValue<'_, String>, String> {
        self.parse_list_hashable::<String>(id, default, |source, id| source.get_string_list(id))
    }

    pub fn parse_dict(
        &self,
        id: &OptionId,
        default: HashMap<String, Val>,
    ) -> Result<DictOptionValue<'_>, String> {
        let mut derivation = None;
        if self.include_derivation {
            let mut derivations = vec![(
                &Source::Default,
                vec![DictEdit {
                    action: DictEditAction::Replace,
                    items: default.clone(),
                }],
            )];
            for (source_type, source) in self.sources.iter() {
                if let Some(dict_edits) = source.get_dict(id)? {
                    derivations.push((source_type, dict_edits));
                }
            }
            derivation = Some(derivations);
        }
        let mut highest_priority_source = &Source::Default;
        let mut edits: Vec<DictEdit> = vec![DictEdit {
            action: DictEditAction::Replace,
            items: default,
        }];
        for (source_type, source) in self.sources.iter() {
            if let Some(dict_edits) = source.get_dict(id)? {
                highest_priority_source = source_type;
                edits.extend(dict_edits);
            }
        }
        Ok(DictOptionValue {
            derivation,
            source: highest_priority_source,
            value: apply_dict_edits(edits.into_iter()),
        })
    }

    // Return the config files used by this parser. Useful for testing config file discovery.
    pub fn get_config_file_paths(&self) -> Vec<String> {
        let mut ret = vec![];
        for source in self.sources.keys() {
            if let Source::Config { ordinal: _, path } = source {
                ret.push(path.to_owned());
            }
        }
        ret
    }

    pub fn get_passthrough_args(&self) -> Result<Option<Vec<String>>, String> {
        Ok(self.command.passthru.clone())
    }

    pub fn get_unconsumed_flags(&self) -> Result<HashMap<Scope, Vec<String>>, String> {
        Ok(self
            .get_flags_reader()?
            .get_tracker()
            .get_unconsumed_flags())
    }

    fn get_flags_reader(&self) -> Result<&FlagsReader, String> {
        if let Some(flags_reader) = self
            .sources
            .get(&Source::Flag)
            .and_then(|source| source.as_any().downcast_ref::<FlagsReader>())
        {
            Ok(flags_reader)
        } else {
            Err("This OptionParser does not have command-line args as a source".to_string())
        }
    }

    // Given a map from section name to valid keys for that section,
    // returns a vec of validation error messages.
    pub fn validate_config(
        &self,
        section_to_valid_keys: &HashMap<String, HashSet<String>>,
    ) -> Vec<String> {
        let mut errors = vec![];
        for (source_type, source) in self.sources.iter() {
            if let Source::Config { ordinal: _, path } = source_type
                && let Some(config_reader) = source.as_any().downcast_ref::<ConfigReader>()
            {
                errors.extend(
                    config_reader
                        .validate(section_to_valid_keys)
                        .iter()
                        .map(|err| format!("{err} in {path}")),
                );
            }
        }
        errors
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
