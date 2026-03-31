// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::hash::{Hash, Hasher};
use std::path::{MAIN_SEPARATOR_STR, Path, PathBuf};
use std::sync::{Arc, LazyLock};

use options::config::{Config, ConfigReader};
use options::fromfile::FromfileExpander;
use options::{BuildRoot, ConfigSource};
use parking_lot::Mutex;

pub type InterpolationMap = BTreeMap<String, String>;

pub static UNQUALIFIED_CONFIG_FILENAME: LazyLock<PathBuf> =
    LazyLock::new(|| PathBuf::from("pantsng.toml"));

// Eq, Hash and PartialEq are implemented manually below, so we can
// exclude the lazily-populated cache fields.
pub struct ConfigFinder {
    buildroot: BuildRoot,
    seed_values: InterpolationMap,
    fromfile_expander: FromfileExpander,
    context: BTreeSet<String>,
    // Lazily-populated caches.
    dir_to_config_paths: Arc<Mutex<HashMap<PathBuf, Vec<PathBuf>>>>,
    parsed_configs: Arc<Mutex<HashMap<PathBuf, Arc<ConfigReader>>>>,
}

impl ConfigFinder {
    pub fn new(
        buildroot: BuildRoot,
        fromfile_expander: FromfileExpander,
        seed_values: InterpolationMap,
        context: BTreeSet<String>,
    ) -> Result<Self, String> {
        Ok(Self {
            buildroot,
            seed_values,
            fromfile_expander,
            context,
            dir_to_config_paths: Arc::new(Mutex::new(HashMap::new())),
            parsed_configs: Arc::new(Mutex::new(HashMap::new())),
        })
    }

    // An equality key that omits the lazily-populated cache fields.
    fn key(
        &self,
    ) -> (
        &BuildRoot,
        &FromfileExpander,
        &InterpolationMap,
        &BTreeSet<String>,
    ) {
        (
            &self.buildroot,
            &self.fromfile_expander,
            &self.seed_values,
            &self.context,
        )
    }

    pub(crate) fn get_config(
        &self,
        config_source: &ConfigSource,
    ) -> Result<Arc<ConfigReader>, String> {
        let mut lock = self.parsed_configs.lock();
        if let Some(config) = lock.get(&config_source.path) {
            return Ok(Arc::clone(config));
        }
        let config = Config::parse(config_source, &self.seed_values)?;
        let config_reader = ConfigReader::new(config, self.fromfile_expander.clone());
        let ret = Arc::new(config_reader);
        lock.insert(config_source.path.to_path_buf(), Arc::clone(&ret));
        Ok(ret)
    }

    // Returns all configs applicable to the given dir and context.
    //
    // See get_applicable_config_files() for how applicability is determined, and for
    // the precedence order of the returned configs.
    pub fn get_applicable_configs(&self, dir: &Path) -> Result<Vec<Arc<ConfigReader>>, String> {
        self.get_applicable_config_files(dir)?
            .into_iter()
            .map(|path| self.get_config(&ConfigSource::from_file(path)?))
            .collect()
    }

    // Returns all config files applicable to the given dir and context.
    //
    // That is, all config files in that dir and in all ancestor dirs up to the build root,
    // all of whose context tags are in the specified context.
    //
    // A valid config file name is `pantsng.toml` or `pantsng_(context tags).toml` where the context
    // tags are dot-separated strings.
    //
    // For example, "pantsng_ci.macos.arm64.toml" has the context tags "ci", "macos" and "arm64",
    // and the file will only be applicable if all those tags are in the given `context` set.
    //
    // Configs are returned in increasing precedence order, i.e., later files have higher
    // precedence than earlier ones. Files in subdirs take precedence over files in parent dirs.
    // Within a single dir precedence is determined by alphabetical order of names of applicable
    // files, with alphabetically later files taking precedence over alphabetically earlier ones.
    //
    // Tags that are all-numeric are ignored for applicability, but can be used to control the
    // precedence order. For example, pantsng_arm64.toml would precede pantsng_ci.toml, but if you
    // want a different order you can name them pantsng_00.ci.toml and pantsng_01.arm64.toml.
    pub fn get_applicable_config_files(&self, dir: &Path) -> Result<Vec<PathBuf>, String> {
        let buildroot = self.buildroot.as_path();
        let dir_abspath = if dir.is_absolute() {
            dir.to_path_buf()
        } else {
            buildroot.join(dir)
        };
        if !dir_abspath.starts_with(buildroot) {
            return Err(format!(
                "{} is not under buildroot {}",
                dir.display(),
                buildroot.display()
            ));
        }

        let mut locked_map = self.dir_to_config_paths.lock();
        let configs =
            self._recursive_get_applicable_config_files(dir_abspath.as_path(), &mut locked_map)?;
        Ok(configs)
    }

    fn _recursive_get_applicable_config_files(
        &self,
        dir_abspath: &Path,
        locked_map: &mut HashMap<PathBuf, Vec<PathBuf>>,
    ) -> Result<Vec<PathBuf>, String> {
        if let Some(val) = locked_map.get(dir_abspath) {
            Ok(val.clone())
        } else {
            let mut config_files = if let Some(parent_abspath) = dir_abspath.parent()
                && parent_abspath.starts_with(self.buildroot.as_path())
            {
                self._recursive_get_applicable_config_files(parent_abspath, locked_map)?
            } else {
                vec![]
            };
            config_files.append(&mut self._find_applicable_config_files_in_dir(dir_abspath)?);
            locked_map.insert(dir_abspath.to_path_buf(), config_files.clone());
            Ok(config_files)
        }
    }

    fn _find_applicable_config_files_in_dir(
        &self,
        dir_abspath: &Path,
    ) -> Result<Vec<PathBuf>, String> {
        let mut dir_configs = vec![];
        // First look at the unqualified pantsng.toml.
        let dir_abspath_str = dir_abspath.to_string_lossy();
        let config_path = dir_abspath.join(UNQUALIFIED_CONFIG_FILENAME.as_path());
        if config_path.exists() {
            dir_configs.push(config_path);
        }
        // Now find all the config files qualified by tags.
        'outer: for item in
            glob::glob(format!("{dir_abspath_str}{MAIN_SEPARATOR_STR}pantsng_*.toml").as_str())
                .map_err(|e| e.to_string())?
        {
            for tag in item
                .as_ref()
                .map_err(|e| e.to_string())?
                .as_path()
                .file_stem()
                .unwrap()
                .to_string_lossy()
                .strip_prefix("pantsng_")
                .unwrap()
                .split(".")
            {
                // All (non-numeric) tags must be in context for this file to be applicable.
                if tag.chars().any(|c| !c.is_ascii_digit()) && !self.context.contains(tag) {
                    continue 'outer;
                }
            }
            dir_configs.push(item.map_err(|e| e.to_string())?);
        }
        dir_configs.sort();
        Ok(dir_configs)
    }
}

impl PartialEq for ConfigFinder {
    fn eq(&self, other: &Self) -> bool {
        self.key() == other.key()
    }
}

impl Eq for ConfigFinder {}

impl Hash for ConfigFinder {
    fn hash<H: Hasher>(&self, state: &mut H) {
        self.key().hash(state);
    }
}
