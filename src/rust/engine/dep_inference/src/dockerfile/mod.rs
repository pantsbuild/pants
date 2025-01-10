// Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::path::PathBuf;

use indexmap::IndexMap;
use lazy_static::lazy_static;
use regex::Regex;
use serde_derive::{Deserialize, Serialize};
use tree_sitter::{Node, Parser};

use crate::code;
use crate::dockerfile::copy::{CopiedFile, CopyFileCollector};
use crate::dockerfile::from::{StageCollector, Tag, TagCollector};

mod copy;
mod from;

include!(concat!(env!("OUT_DIR"), "/dockerfile/constants.rs"));
include!(concat!(env!("OUT_DIR"), "/dockerfile/visitor.rs"));
include!(concat!(env!("OUT_DIR"), "/dockerfile_impl_hash.rs"));

/* todo: This looks leaky now that it is implemented in rust.
Replace with native address parsing? Requires more of address parsing logic
that is currently python rules to move into rust.
*/
lazy_static! {
    static ref ADDRESS_REGEXP: Regex = Regex::new(
        r"(?x)
        ^
        (?://)?  # Optionally root:ed.
        # Optional path.
        [^:\#\s]*
        # Optional target name.
        (?::[^:\#!@?/=\s]+)?
        # Optional generated name.
        (?:\#[^:\#!@?=\s]+)?
        # Optional parametrizations.
        (?:@
          # key=value
          [^=:\s]+=[^,:\s]*
          # Optional additional `,key=value`s
          (?:,[^=:\s]+=[^,:\s]*)*
        )?
        $
    "
    )
    .unwrap();
}

#[derive(Serialize, Deserialize)]
pub struct ParsedDockerfileDependencies {
    pub path: PathBuf,
    pub build_args: Vec<String>,
    pub copy_build_args: Vec<String>,
    pub copy_source_paths: Vec<String>,
    pub from_image_build_args: Vec<String>,
    pub version_tags: IndexMap<String, String>,
}

pub fn get_info(contents: &str, filepath: PathBuf) -> Result<ParsedDockerfileDependencies, String> {
    let mut collector = DockerFileInfoCollector::new(contents);
    collector.collect();
    Ok(ParsedDockerfileDependencies {
        path: filepath,
        version_tags: collector.version_tags,
        build_args: collector.build_args,
        copy_build_args: collector.copy_build_args,
        copy_source_paths: collector.copy_source_paths,
        from_image_build_args: collector.from_image_build_args,
    })
}

struct DockerFileInfoCollector<'a> {
    pub version_tags: IndexMap<String, String>,
    pub build_args: Vec<String>,
    pub seen_build_args: IndexMap<String, Option<String>>,
    pub copy_build_args: Vec<String>,
    pub copy_source_paths: Vec<String>,
    pub from_image_build_args: Vec<String>,
    stage_counter: usize,
    code: &'a str,
}

impl DockerFileInfoCollector<'_> {
    pub fn new(code: &'_ str) -> DockerFileInfoCollector<'_> {
        DockerFileInfoCollector {
            version_tags: IndexMap::default(),
            seen_build_args: IndexMap::default(),
            build_args: Vec::default(),
            copy_build_args: Vec::default(),
            copy_source_paths: Vec::default(),
            from_image_build_args: Vec::default(),
            stage_counter: 0,
            code,
        }
    }

    fn get_build_arg_value(&self, key: &str) -> Option<&str> {
        if let Some(maybe_value) = self.seen_build_args.get(key) {
            maybe_value
                .as_deref()
                .map(|value| value.trim_matches(|c| c == '\'' || c == '"'))
        } else {
            None
        }
    }

    fn get_build_arg_reference(&self, key: &str) -> Option<&str> {
        self.get_build_arg_value(key)
            .filter(|s| ADDRESS_REGEXP.is_match(s))
    }

    pub fn collect(&mut self) {
        let mut parser = Parser::new();
        parser
            .set_language(tree_sitter_dockerfile::language())
            .expect("Error loading Dockerfile grammar");
        let parsed = parser.parse(self.code, None);
        let tree = parsed.unwrap();
        let mut cursor = tree.walk();

        self.walk(&mut cursor);
    }
}

impl Visitor for DockerFileInfoCollector<'_> {
    fn visit_from_instruction(&mut self, node: Node) -> ChildBehavior {
        let mut cursor = node.walk();
        let mut tag_collector = TagCollector::new(self.code);
        tag_collector.walk(&mut cursor);
        let tag = match tag_collector.tag {
            Tag::Default => Some("latest".to_string()),
            Tag::BuildArg(arg) => {
                self.from_image_build_args.extend(
                    self.get_build_arg_reference(arg)
                        .map(|val| format!("{arg}={val}")),
                );
                Some(format!("build-arg:{arg}"))
            }
            Tag::Explicit(e) => Some(e.to_string()),
            Tag::None => None,
        };
        if let Some(tag) = tag {
            let mut stage_collector = StageCollector::new(self.code);
            stage_collector.walk(&mut cursor);
            self.version_tags
                .insert(stage_collector.get_stage(self.stage_counter), tag);
        }
        self.stage_counter += 1;
        ChildBehavior::Ignore
    }

    fn visit_copy_instruction(&mut self, node: Node) -> ChildBehavior {
        let mut file_collector = CopyFileCollector::new(self.code);
        file_collector.walk(&mut node.walk());
        let mut files = file_collector.files;
        if files.is_empty() {
            return ChildBehavior::Visit;
        } else {
            files.pop();
        }
        for file in files {
            match file {
                CopiedFile::Arg(arg) => self.copy_build_args.extend(
                    self.get_build_arg_reference(arg)
                        .map(|val| format!("{arg}={val}")),
                ),
                CopiedFile::Path(file) => self.copy_source_paths.push(file.to_string()),
            }
        }
        ChildBehavior::Visit
    }

    fn visit_arg_instruction(&mut self, node: Node) -> ChildBehavior {
        if let Some(arg) = code::at(self.code, node).strip_prefix("ARG").map(str::trim) {
            self.build_args.push(arg.to_string());
            let mut split = arg.splitn(2, '=');
            self.seen_build_args.insert(
                split
                    .next()
                    .expect("First value from split is always present.")
                    .trim()
                    .to_string(),
                split.next().map(str::trim).map(str::to_string),
            );
        };
        ChildBehavior::Ignore
    }
}

#[cfg(test)]
mod tests;
