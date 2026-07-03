// Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use tree_sitter::Node;

use crate::code;
use crate::dockerfile::{ChildBehavior, Visitor};

pub(crate) struct TagCollector<'a> {
    pub tag: Tag<'a>,
    pub image_arg: Option<&'a str>,
    image_name: Option<&'a str>,
    code: &'a str,
}

impl<'a> TagCollector<'a> {
    pub fn new(code: &'a str) -> Self {
        Self {
            tag: Tag::None,
            image_arg: None,
            image_name: None,
            code,
        }
    }
}

#[derive(Debug, Eq, PartialEq)]
pub(crate) enum Tag<'a> {
    Explicit(&'a str),
    BuildArg(&'a str),
    Default,
    None,
}

impl Visitor for TagCollector<'_> {
    fn visit_variable(&mut self, node: Node) -> ChildBehavior {
        if let Some(image_name) = self.image_name {
            let var = code::at(self.code, node);
            let is_var = |s: &str| {
                s.strip_prefix('$') == Some(var)
                    || s.strip_prefix("${").and_then(|b| b.strip_suffix('}')) == Some(var)
            };
            // Whole image name is a build arg: an inferred dependency.
            if is_var(image_name) {
                self.image_arg = Some(var);
            }
            // Final path segment is a build arg: the base image tag.
            let last_segment = image_name.rsplit('/').next().unwrap_or(image_name);
            if is_var(last_segment) {
                self.tag = Tag::BuildArg(var);
            }
        }
        ChildBehavior::Ignore
    }

    fn visit_image_name(&mut self, node: Node) -> ChildBehavior {
        self.image_name = Some(code::at(self.code, node));
        if self.tag == Tag::None {
            self.tag = Tag::Default
        }
        ChildBehavior::Visit
    }

    fn visit_image_tag(&mut self, node: Node) -> ChildBehavior {
        self.image_arg = None;
        self.tag = code::at(self.code, node)
            .strip_prefix(':')
            .map(Tag::Explicit)
            .unwrap_or(Tag::Default);
        ChildBehavior::Ignore
    }

    fn visit_image_digest(&mut self, _node: Node) -> ChildBehavior {
        self.image_arg = None;
        if matches!(self.tag, Tag::Default | Tag::BuildArg(_)) {
            self.tag = Tag::None
        }
        ChildBehavior::Ignore
    }
}

pub(crate) struct StageCollector<'a> {
    pub stage: Option<&'a str>,
    code: &'a str,
}

impl<'a> StageCollector<'a> {
    pub fn new(code: &'a str) -> StageCollector<'a> {
        Self { stage: None, code }
    }

    pub fn get_stage(self, stage_number: usize) -> String {
        self.stage
            .map(str::to_string)
            .unwrap_or_else(|| format!("stage{stage_number}"))
    }
}

impl Visitor for StageCollector<'_> {
    fn visit_image_alias(&mut self, node: Node) -> ChildBehavior {
        self.stage = Some(code::at(self.code, node));
        ChildBehavior::Ignore
    }
}
