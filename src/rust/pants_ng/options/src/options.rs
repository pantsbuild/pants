// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::hash::{Hash, Hasher};
use std::path::{Path, PathBuf};
use std::sync::Arc;

use options::config::{Config, ConfigReader};
use sha2::{Digest, Sha256};

use hashing::Fingerprint;
use options::env::EnvReader;
use options::fromfile::FromfileExpander;
use options::pants_ng_flags::PantsNgFlagsReader;
use options::{
    BuildRoot, ConfigSource, DictOptionValue, Env, ListOptionValue, OptionId, OptionParser,
    OptionalOptionValue, OptionsSource, Scope, Source, Val,
};

use crate::config::{ConfigFinder, InterpolationMap};
use crate::pants_invocation::PantsInvocation;

// A set of source paths and the options that apply to those sources.
pub struct SourcePartition {
    pub paths: Vec<PathBuf>,
    pub options_reader: OptionsReader,
}

pub struct OptionsReader {
    option_parser: OptionParser,
    // OptionParser doesn't (and cannot easily) implement Hash and Eq, so we
    // custom implement via a fingerprint.
    fingerprint: Fingerprint,
}

impl PartialEq for OptionsReader {
    fn eq(&self, other: &Self) -> bool {
        self.fingerprint == other.fingerprint
    }
}

impl Eq for OptionsReader {}

impl Hash for OptionsReader {
    fn hash<H: Hasher>(&self, state: &mut H) {
        self.fingerprint.hash(state);
    }
}

impl OptionsReader {
    pub fn new(
        fromfile_expander: &FromfileExpander,
        flags: HashMap<Scope, HashMap<String, Vec<Option<String>>>>,
        env: &Env,
        // If a caller doesn't provider a ConfigReader for the ConfigSource, we'll create one.
        // Production code will call this with a memoized ConfigReader, but this is useful for
        // tests that don't care about that memoization.
        configs: Vec<(ConfigSource, Option<Arc<ConfigReader>>)>,
    ) -> Result<Self, String> {
        let mut hasher = Sha256::new();
        fromfile_expander.add_to_sha256(&mut hasher);

        let mut sources: BTreeMap<Source, Arc<dyn OptionsSource>> = BTreeMap::new();
        for (ordinal, config) in configs.into_iter().enumerate() {
            let (config_source, config_reader) = config;
            let config_reader = if let Some(cr) = config_reader {
                cr
            } else {
                Arc::new(ConfigReader::new(
                    Config::parse(&config_source, &BTreeMap::new())?,
                    fromfile_expander.clone(),
                ))
            };
            config_reader.add_to_sha256(&mut hasher);
            sources.insert(
                Source::Config {
                    ordinal,
                    path: config_source.path.to_string_lossy().to_string(),
                },
                config_reader,
            );
        }

        for (k, v) in env.env.iter() {
            hasher.update(k.as_bytes());
            hasher.update(v.as_bytes());
        }
        sources.insert(
            Source::Env,
            Arc::new(EnvReader::new(env.clone(), fromfile_expander.clone())),
        );

        for (scope, scoped_flags) in flags.iter() {
            hasher.update(scope.name().as_bytes());
            for (k, vals) in scoped_flags {
                hasher.update(k.as_bytes());
                for v in vals {
                    if let Some(v) = v {
                        hasher.update(b"Some");
                        hasher.update(v.as_bytes());
                    } else {
                        hasher.update(b"None");
                    }
                }
            }
        }
        sources.insert(
            Source::Flag,
            Arc::new(PantsNgFlagsReader::new(flags, fromfile_expander.clone())),
        );
        Ok(Self {
            option_parser: OptionParser::new_pants_ng(sources, false),
            fingerprint: Fingerprint::from_bytes(hasher.finalize()),
        })
    }

    // Option value accessors are currently implemented as passthroughs to an og OptionParser.
    pub fn parse_bool_optional(
        &self,
        id: &OptionId,
        default: Option<bool>,
    ) -> Result<OptionalOptionValue<'_, bool>, String> {
        self.option_parser.parse_bool_optional(id, default)
    }

    pub fn parse_int_optional(
        &self,
        id: &OptionId,
        default: Option<i64>,
    ) -> Result<OptionalOptionValue<'_, i64>, String> {
        self.option_parser.parse_int_optional(id, default)
    }

    pub fn parse_float_optional(
        &self,
        id: &OptionId,
        default: Option<f64>,
    ) -> Result<OptionalOptionValue<'_, f64>, String> {
        self.option_parser.parse_float_optional(id, default)
    }

    pub fn parse_string_optional(
        &self,
        id: &OptionId,
        default: Option<&str>,
    ) -> Result<OptionalOptionValue<'_, String>, String> {
        self.option_parser.parse_string_optional(id, default)
    }

    pub fn parse_bool_list(
        &self,
        id: &OptionId,
        default: Vec<bool>,
    ) -> Result<ListOptionValue<'_, bool>, String> {
        self.option_parser.parse_bool_list(id, default)
    }

    pub fn parse_int_list(
        &self,
        id: &OptionId,
        default: Vec<i64>,
    ) -> Result<ListOptionValue<'_, i64>, String> {
        self.option_parser.parse_int_list(id, default)
    }

    pub fn parse_float_list(
        &self,
        id: &OptionId,
        default: Vec<f64>,
    ) -> Result<ListOptionValue<'_, f64>, String> {
        self.option_parser.parse_float_list(id, default)
    }

    pub fn parse_string_list(
        &self,
        id: &OptionId,
        default: Vec<String>,
    ) -> Result<ListOptionValue<'_, String>, String> {
        self.option_parser.parse_string_list(id, default)
    }

    pub fn parse_dict(
        &self,
        id: &OptionId,
        default: HashMap<String, Val>,
    ) -> Result<DictOptionValue<'_>, String> {
        self.option_parser.parse_dict(id, default)
    }
}

#[derive(Eq, Hash, PartialEq)]
pub struct Options {
    pants_invocation: PantsInvocation,
    env: Env,
    config_finder: ConfigFinder,
    fromfile_expander: FromfileExpander,
    include_derivation: bool,
}

impl Options {
    pub fn new(
        pants_invocation: &PantsInvocation,
        env: Env,
        buildroot: Option<BuildRoot>,
        context: Option<Vec<String>>,
        include_derivation: bool,
    ) -> Result<Self, String> {
        // NB: Unlike og Pants, which allowed any env var as a seed value, we require seed values
        //     to start with PANTS_, the same as option values. This is so we can avoid spurious
        //     invalidation due to unconsumed env vars changing.
        let env = Env {
            env: env
                .env
                .into_iter()
                .filter_map(|(k, v)| {
                    if k.starts_with("PANTS_") && !k.starts_with("PANTS_SANDBOXER_BINARY_PATH") {
                        Some((k, v))
                    } else {
                        None
                    }
                })
                .collect(),
        };
        let buildroot = buildroot.map(Ok).unwrap_or_else(BuildRoot::find)?;
        let mut seed_values = InterpolationMap::from_iter(
            env.env.iter().map(|(k, v)| (format!("env.{k}"), v.clone())),
        );
        seed_values.extend([
            ("buildroot".to_string(), buildroot.convert_to_string()?),
            ("homedir".to_string(), shellexpand::tilde("~").into_owned()),
            ("user".to_string(), whoami::username()),
            // TODO: Support setting custom workdir and distdir? The current
            //   parser supports this, but it seems pretty esoteric.
            ("pants_workdir".to_string(), ".pants.d".to_string()),
            ("pants_distdir".to_string(), "dist".to_string()),
        ]);

        let fromfile_expander = FromfileExpander::relative_to(buildroot.clone());
        let context = BTreeSet::from_iter(context.unwrap_or_else(|| {
            // NB: These are compile-time constants. If running a binary on a foreign arch via
            // translation/emulation (e.g., Rosetta) they may not reflect user intent. But that
            // seems like an esoteric case to worry about right now.
            vec![
                std::env::consts::OS.to_string(),
                std::env::consts::ARCH.to_string(),
                std::env::consts::FAMILY.to_string(),
            ]
        }));
        let config_finder =
            ConfigFinder::new(buildroot, fromfile_expander.clone(), seed_values, context)?;

        // TODO: Support rcfiles.
        // TODO: Support CLI aliases?

        Ok(Self {
            pants_invocation: pants_invocation.clone(),
            env,
            config_finder,
            fromfile_expander,
            include_derivation,
        })
    }

    fn get_options_reader_for_configs(
        &self,
        config_files: Vec<PathBuf>,
    ) -> Result<OptionsReader, String> {
        OptionsReader::new(
            &self.fromfile_expander,
            self.pants_invocation.get_flags(),
            &self.env,
            config_files
                .iter()
                .map(|config_file| {
                    let config_source = ConfigSource::from_file(config_file)?;
                    let config_reader = self.config_finder.get_config(&config_source)?;
                    Ok((config_source, Some(config_reader)))
                })
                .collect::<Result<_, String>>()?,
        )
    }

    pub fn get_options_reader_for_dir(&self, dir: &Path) -> Result<OptionsReader, String> {
        self.get_options_reader_for_configs(self.config_finder.get_applicable_config_files(dir)?)
    }
}
