// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::pants_invocation::PantsInvocation;
use options::BuildRoot;
use options::ConfigSource;
use options::Env;
use options::config::Config;
use options::fromfile::FromfileExpander;
use std::collections::HashMap;
use std::collections::HashSet;
use std::fs::canonicalize;
use std::path::MAIN_SEPARATOR_STR;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;

type InterpolationMap = HashMap<String, String>;

#[allow(dead_code)]
pub struct OptionsParser {
    buildroot: BuildRoot,
    fromfile_expander: FromfileExpander,
    seed_values: InterpolationMap,
    // Populated lazily as we encounter config files.
    parsed_configs: Arc<Mutex<HashMap<PathBuf, Arc<Config>>>>,
    env: Env,
    invocation: PantsInvocation,
}

impl OptionsParser {
    pub fn new(
        buildroot: Option<BuildRoot>,
        seed_values: InterpolationMap,
        env: Env,
        invocation: PantsInvocation,
    ) -> Result<Self, String> {
        let buildroot = buildroot.unwrap_or(BuildRoot::find()?);
        let fromfile_expander = FromfileExpander::relative_to(buildroot.clone());

        Ok(Self {
            buildroot,
            fromfile_expander,
            seed_values,
            parsed_configs: Arc::new(Mutex::new(HashMap::new())),
            env,
            invocation,
        })
    }

    #[allow(dead_code)]
    fn get_config(&mut self, path: &Path) -> Result<Arc<Config>, String> {
        let mut lock = self.parsed_configs.lock().map_err(|e| e.to_string())?;
        if let Some(config) = lock.get(path) {
            return Ok(Arc::clone(config));
        }
        let config = Config::parse(&ConfigSource::from_file(path)?, &self.seed_values)?;
        let ret = Arc::new(config);
        lock.insert(path.to_path_buf(), Arc::clone(&ret));
        Ok(ret)
    }

    // Returns all configs applicable to the given dir and context.
    // That is, all config files in that dir and in all ancestor dirs up to the build root,
    // all of whose context tags are in the specified context.
    //
    // A context tag is any dot-separated string between "pants" and ".toml".
    // For example, "pants.ci.macos.arm64.toml" has the context tags "ci", "macos" and "arm64",
    // and the file will only be applicable if all those tags are in the given `context` set.
    // The context is a string like "ci" or "macos.x86_64"
    #[allow(dead_code)]
    fn get_applicable_configs(
        &mut self,
        dir: &Path,
        context: &HashSet<String>,
    ) -> Result<Vec<Arc<Config>>, String> {
        let buildroot = self.buildroot.as_path();
        let canonical_dir = canonicalize(dir).map_err(|e| e.to_string())?;
        let mut dir = canonical_dir.as_path();
        if dir.is_absolute() {
            dir = dir.strip_prefix(buildroot).map_err(|e| e.to_string())?
        }
        let unqualified_config_file = PathBuf::from("pants.toml");
        let mut configs = vec![];

        // For each ancestor dir, find all applicable config files in that dir.
        for ancestor in dir.ancestors() {
            // First look at the unqualified pants.toml.
            let ancestor_str = ancestor.to_string_lossy();
            let config_path = ancestor.join(&unqualified_config_file);
            if config_path.exists() {
                configs.push(self.get_config(config_path.as_path())?);
            }
            // Now find all the config files qualified by tags.
            'outer: for item in
                glob::glob(format!("{ancestor_str}{MAIN_SEPARATOR_STR}pants.*.toml").as_str())
                    .map_err(|e| e.to_string())?
            {
                for tag in item
                    .as_ref()
                    .map_err(|e| e.to_string())?
                    .as_path()
                    .file_stem()
                    .unwrap()
                    .to_string_lossy()
                    .strip_prefix("pants.")
                    .unwrap()
                    .split(".")
                {
                    // All tags must be in context for this config file to be considered.
                    if !context.contains(tag) {
                        continue 'outer;
                    }
                }
                configs.push(self.get_config(&item.map_err(|e| e.to_string())?)?);
            }
        }

        Ok(configs)
    }
}
