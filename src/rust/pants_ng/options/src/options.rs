// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::config::ConfigFinder;
use crate::config::InterpolationMap;
use crate::pants_invocation::PantsInvocation;
use options::OptionParser;
use options::Source;
use options::env::EnvReader;
use options::fromfile::FromfileExpander;
use options::pants_ng_flags::PantsNgFlagsReader;
use options::{BuildRoot, Env, OptionsSource};
use std::collections::BTreeMap;
use std::collections::HashSet;
use std::path::Path;
use std::sync::Arc;

pub struct OptionsReader {
    #[allow(dead_code)]
    options_parser: OptionParser,
}

pub struct Options {
    pants_invocation: PantsInvocation,
    env: Env,
    config_finder: ConfigFinder,
    context: HashSet<String>,
    fromfile_expander: FromfileExpander,
    include_derivation: bool,
}

impl Options {
    pub fn new(
        pants_invocation: PantsInvocation,
        env: Env,
        buildroot: Option<BuildRoot>,
        seed_values: InterpolationMap,
        context: Vec<String>,
        include_derivation: bool,
    ) -> Result<Self, String> {
        let buildroot = buildroot.unwrap_or(BuildRoot::find()?);
        let fromfile_expander = FromfileExpander::relative_to(buildroot.clone());
        let config_finder = ConfigFinder::new(buildroot, fromfile_expander.clone(), seed_values)?;
        let context = HashSet::from_iter(context);

        // TODO: Support rcfiles.
        // TODO: Support CLI aliases?
        // TODO: Support reading custom workdir and distdir from env/args? The current
        //   parser supports this, but it seems pretty esoteric.

        Ok(Self {
            pants_invocation,
            env,
            config_finder,
            context,
            fromfile_expander,
            include_derivation,
        })
    }

    pub fn get_options_reader_for_dir(&self, dir: &Path) -> Result<OptionsReader, String> {
        let mut sources: BTreeMap<Source, Arc<dyn OptionsSource>> = BTreeMap::new();
        for (ordinal, config_file) in self
            .config_finder
            .get_applicable_config_files(dir, &self.context)?
            .iter()
            .enumerate()
        {
            let config_reader = self.config_finder.get_config(config_file)?;
            sources.insert(
                Source::Config {
                    ordinal,
                    path: config_file.to_string_lossy().to_string(),
                },
                config_reader,
            );
        }

        sources.insert(
            Source::Env,
            Arc::new(EnvReader::new(
                self.env.clone(),
                self.fromfile_expander.clone(),
            )),
        );
        sources.insert(
            Source::Flag,
            Arc::new(PantsNgFlagsReader::new(
                self.pants_invocation.get_flags(),
                self.fromfile_expander.clone(),
            )),
        );
        Ok(OptionsReader {
            options_parser: OptionParser::new_pants_ng(sources, self.include_derivation),
        })
    }
}
