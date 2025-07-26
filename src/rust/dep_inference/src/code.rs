// Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use tree_sitter::{Node, Range};

pub fn at<'a>(code: &'a str, node: Node) -> &'a str {
    at_range(code, node.range())
}

pub fn at_range(code: &str, range: Range) -> &str {
    &code[range.start_byte..range.end_byte]
}
