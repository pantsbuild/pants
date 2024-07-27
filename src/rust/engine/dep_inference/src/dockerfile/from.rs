// Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use tree_sitter::Node;

use crate::code;
use crate::dockerfile::{ChildBehavior, Visitor};

pub(crate) struct TagCollector<'a> {
    pub tag: Tag<'a>,
    is_arg: bool,
    code: &'a str,
}

impl<'a> TagCollector<'a> {
    pub fn new(code: &'a str) -> Self {
        Self {
            tag: Tag::None,
            is_arg: false,
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
        if self.is_arg {
            self.tag = Tag::BuildArg(code::at(self.code, node));
        }
        ChildBehavior::Ignore
    }

    fn visit_image_spec(&mut self, node: Node) -> ChildBehavior {
        if code::at(self.code, node).trim().starts_with('$') {
            self.is_arg = true;
        }
        ChildBehavior::Visit
    }

    fn visit_image_name(&mut self, _: Node) -> ChildBehavior {
        if self.tag == Tag::None {
            self.tag = Tag::Default
        }
        ChildBehavior::Visit
    }

    fn visit_image_tag(&mut self, node: Node) -> ChildBehavior {
        self.tag = code::at(self.code, node)
            .strip_prefix(':')
            .map(Tag::Explicit)
            .unwrap_or(Tag::Default);
        ChildBehavior::Ignore
    }

    fn visit_image_digest(&mut self, _node: Node) -> ChildBehavior {
        if self.tag == Tag::Default {
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
            .unwrap_or_else(|| format!("stage{}", stage_number))
    }
}

impl Visitor for StageCollector<'_> {
    fn visit_image_alias(&mut self, node: Node) -> ChildBehavior {
        self.stage = Some(code::at(self.code, node));
        ChildBehavior::Ignore
    }
}
