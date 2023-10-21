// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::glob_matching::PathGlob;
use crate::{GitignoreStyleExcludes, GlobExpansionConjunction, PathGlobs, StrictGlobMatching};

#[test]
fn path_globs_create_distinguishes_between_includes_and_excludes() {
    let include_globs = vec!["foo.rs".to_string(), "bar.rs".to_string()];
    let parsed_exclude_globs = vec!["ignore.rs".to_string(), "**/*.rs".to_string()];

    let mut glob_inputs: Vec<String> = vec![];
    glob_inputs.extend_from_slice(&include_globs);
    glob_inputs.extend(parsed_exclude_globs.iter().map(|glob| format!("!{glob}")));

    let pg = PathGlobs::new(
        glob_inputs,
        StrictGlobMatching::Ignore,
        GlobExpansionConjunction::AllMatch,
    )
    .parse()
    .expect("Path globs failed to be created");

    assert_eq!(
        pg.include,
        PathGlob::spread_filespecs(include_globs).expect("Include globs failed to expand")
    );
    assert_eq!(
        pg.exclude.patterns,
        GitignoreStyleExcludes::create(parsed_exclude_globs)
            .expect("Exclude globs failed to expand")
            .patterns
    );
}
