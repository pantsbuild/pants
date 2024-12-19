// Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use crate::code;
use crate::dockerfile::{ChildBehavior, Visitor};
use tree_sitter::Node;

#[derive(Debug, Eq, PartialEq)]
pub(crate) enum CopiedFile<'a> {
    Path(&'a str),
    Arg(&'a str),
}

pub(crate) struct CopyFileCollector<'a> {
    pub files: Vec<CopiedFile<'a>>,
    is_from: bool,
    code: &'a str,
}

impl<'a> CopyFileCollector<'a> {
    pub fn new(code: &'a str) -> Self {
        Self {
            code,
            is_from: false,
            files: Vec::default(),
        }
    }
}

impl Visitor for CopyFileCollector<'_> {
    fn visit_variable(&mut self, node: Node) -> ChildBehavior {
        if self.is_from {
            ChildBehavior::Ignore
        } else if let Some(CopiedFile::Path(_)) = self.files.last() {
            self.replace_last_path_with_encountered_variable_name(node)
        } else {
            ChildBehavior::Visit
        }
    }

    fn visit_path(&mut self, node: Node) -> ChildBehavior {
        if self.is_from {
            return ChildBehavior::Ignore;
        }
        self.files.push(CopiedFile::Path(code::at(self.code, node)));
        ChildBehavior::Visit
    }

    fn visit_param(&mut self, node: Node) -> ChildBehavior {
        if code::at(self.code, node).contains("--from") {
            self.is_from = true;
            ChildBehavior::Ignore
        } else {
            ChildBehavior::Visit
        }
    }
}

impl CopyFileCollector<'_> {
    /// A variable "VAR" is always wrapped in a path "$VAR".
    /// This method replaces the latest encountered path
    /// with the next seen variable, assuming it is the variable inside the path.
    ///
    /// E.g.
    /// ```dockerfile
    /// ARG VAR
    /// COPY $VAR to/here
    ///       |--> variable
    ///      |---> path
    ///
    /// ```
    fn replace_last_path_with_encountered_variable_name(&mut self, node: Node) -> ChildBehavior {
        self.files.pop();
        self.files.push(CopiedFile::Arg(code::at(self.code, node)));
        ChildBehavior::Ignore
    }
}
