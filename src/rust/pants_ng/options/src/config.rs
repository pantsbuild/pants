// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use options::config::{Config, ConfigReader};
use options::fromfile::FromfileExpander;
use options::{BuildRoot, ConfigSource};
use parking_lot::Mutex;
use std::collections::{HashMap, HashSet};
use std::fs::canonicalize;
use std::path::{MAIN_SEPARATOR_STR, Path, PathBuf};
use std::sync::Arc;

pub type InterpolationMap = HashMap<String, String>;

pub struct ConfigFinder {
    buildroot: BuildRoot,
    seed_values: InterpolationMap,
    fromfile_expander: FromfileExpander,
    // Populated lazily as we encounter config files.
    parsed_configs: Arc<Mutex<HashMap<PathBuf, Arc<ConfigReader>>>>,
}

impl ConfigFinder {
    pub fn new(buildroot: BuildRoot, seed_values: InterpolationMap) -> Result<Self, String> {
        let fromfile_expander = FromfileExpander::relative_to(buildroot.clone());
        Ok(Self {
            buildroot,
            seed_values,
            fromfile_expander,
            parsed_configs: Arc::new(Mutex::new(HashMap::new())),
        })
    }

    fn get_config(&self, path: &Path) -> Result<Arc<ConfigReader>, String> {
        let mut lock = self.parsed_configs.lock();
        if let Some(config) = lock.get(path) {
            return Ok(Arc::clone(config));
        }
        let config = Config::parse(&ConfigSource::from_file(path)?, &self.seed_values)?;
        let config_reader = ConfigReader::new(config, self.fromfile_expander.clone());
        let ret = Arc::new(config_reader);
        lock.insert(path.to_path_buf(), Arc::clone(&ret));
        Ok(ret)
    }

    // Returns all configs applicable to the given dir and context.
    //
    // See get_applicable_config_files() for how applicability is determined, and for
    // the precedence order of the returned configs.
    pub fn get_applicable_configs(
        &self,
        dir: &Path,
        context: &HashSet<String>,
    ) -> Result<Vec<Arc<ConfigReader>>, String> {
        self.get_applicable_config_files(dir, context)?
            .into_iter()
            .map(|path| self.get_config(path.as_path()))
            .collect()
    }

    // Returns all config files applicable to the given dir and context.
    //
    // That is, all config files in that dir and in all ancestor dirs up to the build root,
    // all of whose context tags are in the specified context.
    //
    // A valid config file name is `pants.toml` or `pants_(context tags).toml` where the context
    // tags are dot-separated strings.
    //
    // For example, "pants_ci.macos.arm64.toml" has the context tags "ci", "macos" and "arm64",
    // and the file will only be applicable if all those tags are in the given `context` set.
    //
    // Configs are returned in precedence order, with later files overriding earlier ones.
    // Files in subdirs take precedence over files in parent dirs. Within a single dir precedence
    // is determined by alphabetical order of names of applicable files.
    //
    // Tags that are all-numeric are ignored for applicability, but can be used to control the
    // precedence order. For example, pants_arm64.toml would precede pants_ci.toml, but if
    // want a different order you can name them pants_00.ci.toml and pants_01.arm64.toml.
    pub fn get_applicable_config_files(
        &self,
        dir: &Path,
        context: &HashSet<String>,
    ) -> Result<Vec<PathBuf>, String> {
        let buildroot = canonicalize(self.buildroot.as_path()).map_err(|e| e.to_string())?;
        let dir = if dir.is_relative() {
            buildroot.join(dir)
        } else {
            dir.to_path_buf()
        };
        if !dir.starts_with(&buildroot) {
            return Err(format!(
                "Path {} is not under buildroot {}",
                dir.display(),
                buildroot.display()
            ));
        }
        let dir = canonicalize(dir).map_err(|e| e.to_string())?;

        let unqualified_config_file = PathBuf::from("pants.toml");
        let mut configs = vec![];

        // For each ancestor dir, find all applicable config files in that dir.
        for ancestor in dir.ancestors() {
            let mut dir_configs = vec![];
            // First look at the unqualified pants.toml.
            let ancestor_str = ancestor.to_string_lossy();
            let config_path = ancestor.join(&unqualified_config_file);
            if config_path.exists() {
                dir_configs.push(config_path);
            }
            // Now find all the config files qualified by tags.
            'outer: for item in
                glob::glob(format!("{ancestor_str}{MAIN_SEPARATOR_STR}pants_*.toml").as_str())
                    .map_err(|e| e.to_string())?
            {
                for tag in item
                    .as_ref()
                    .map_err(|e| e.to_string())?
                    .as_path()
                    .file_stem()
                    .unwrap()
                    .to_string_lossy()
                    .strip_prefix("pants_")
                    .unwrap()
                    .split(".")
                {
                    // All (non-numeric) tags must be in context for this file to be applicable.
                    if tag.chars().any(|c| !c.is_ascii_digit()) && !context.contains(tag) {
                        continue 'outer;
                    }
                }
                dir_configs.push(item.map_err(|e| e.to_string())?);
            }
            // Alphabetical order is precedence order, but we reverse, so that reversing
            // the entire configs vector below leaves us with the right order.
            dir_configs.sort();
            dir_configs.reverse();
            configs.append(&mut dir_configs);

            if ancestor == buildroot {
                break;
            }
        }

        // We discover configs from deep to shallow, but we want to process them from
        // shallow to deep, so that deeper configs override shallower ones.
        configs.reverse();
        Ok(configs)
    }
}
