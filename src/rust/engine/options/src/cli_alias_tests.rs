// Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::cli_alias::AliasMap;
use crate::cli_alias::{self, AliasExpansion};
use maplit::{hashmap, hashset};
use std::collections::HashMap;

// Convenience functions for turning data structures containing static strings into the same
// structure but with owned String instances.
fn owned_vec(x: Vec<&str>) -> Vec<String> {
    x.into_iter().map(|x| x.to_string()).collect::<Vec<_>>()
}

fn owned_map(x: HashMap<&str, &str>) -> HashMap<String, String> {
    x.into_iter()
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect::<HashMap<_, _>>()
}

#[test]
fn test_expand_no_aliases() {
    let args = owned_vec(vec!["foo", "--bar=baz", "qux"]);
    assert_eq!(
        args,
        cli_alias::expand_aliases(args.clone(), &AliasMap(hashmap! {}))
    );
}

#[test]
fn test_expand_alias() {
    #[track_caller]
    fn do_test(replacement: &str, expected: Vec<&str>) {
        let expected = owned_vec(expected);

        let expanded_word = cli_alias::expand_aliases(
            owned_vec(vec!["alias"]),
            &cli_alias::create_alias_map(
                None,
                &hashmap! {"alias".to_string() => replacement.to_string()},
            )
            .unwrap(),
        );
        assert_eq!(expected, expanded_word);

        let expanded_flag = cli_alias::expand_aliases(
            owned_vec(vec!["--alias"]),
            &cli_alias::create_alias_map(
                None,
                &hashmap! {"--alias".to_string() => replacement.to_string()},
            )
            .unwrap(),
        );
        assert_eq!(expected, expanded_flag);
    }

    do_test("--arg1", vec!["--arg1"]);
    do_test("--arg1 --arg2", vec!["--arg1", "--arg2"]);
    do_test("--arg=value --option", vec!["--arg=value", "--option"]);
    do_test(
        "--arg=value --option flag",
        vec!["--arg=value", "--option", "flag"],
    );
    do_test("--arg 'quoted value'", vec!["--arg", "quoted value"]);
}

#[test]
fn test_expand_args() {
    #[track_caller]
    fn do_test(args: Vec<&str>, expected: Vec<&str>) {
        let aliases = cli_alias::create_alias_map(
            None,
            &hashmap! {"alias".to_string() => "--flag goal".to_string()},
        )
        .unwrap();
        assert_eq!(
            owned_vec(expected),
            cli_alias::expand_aliases(owned_vec(args), &aliases)
        );
    }

    do_test(
        vec!["some", "alias", "target"],
        vec!["some", "--flag", "goal", "target"],
    );
    // Don't touch pass through args.
    do_test(
        vec!["some", "--", "alias", "target"],
        vec!["some", "--", "alias", "target"],
    );
}

#[test]
fn test_expand_args_flag() {
    #[track_caller]
    fn do_test(args: Vec<&str>, expected: Vec<&str>) {
        let aliases = cli_alias::create_alias_map(
            None,
            &hashmap! {"--alias".to_string() => "--flag goal".to_string()},
        )
        .unwrap();
        assert_eq!(
            owned_vec(expected),
            cli_alias::expand_aliases(owned_vec(args), &aliases)
        );
    }

    do_test(
        vec!["some", "--alias", "target"],
        vec!["some", "--flag", "goal", "target"],
    );
    // Don't touch pass through args.
    do_test(
        vec!["some", "--", "--alias", "target"],
        vec!["some", "--", "--alias", "target"],
    );
}

#[test]
fn test_expand_args_flag_with_metavar() {
    #[track_caller]
    fn do_test(args: Vec<&str>, expected: Vec<&str>) {
        let aliases = cli_alias::create_alias_map(
            None,
            &hashmap! { "--alias=FOO".to_string() => "--flag=$FOO --flag=PRE$FOO@ --flag FOO $FOO --flag2=PRE${FOO}POST".to_string() },
        )
        .unwrap();
        assert_eq!(
            owned_vec(expected),
            cli_alias::expand_aliases(owned_vec(args), &aliases)
        );
    }

    do_test(
        vec!["some", "--alias=grok", "goal", "target"],
        vec![
            "some",
            "--flag=grok",
            "--flag=PREgrok@",
            "--flag",
            "FOO",
            "grok",
            "--flag2=PREgrokPOST",
            "goal",
            "target",
        ],
    );

    // Don't touch pass through args.
    do_test(
        vec!["some", "--", "--alias=grok", "target"],
        vec!["some", "--", "--alias=grok", "target"],
    );
}

#[test]
fn test_nested_alias() {
    assert_eq!(
        AliasMap(hashmap! {
            "basic".to_string() => AliasExpansion::Bare(vec!["goal".to_string()]),
            "nested".to_string() => AliasExpansion::Bare(vec!["--option=advanced".to_string(), "goal".to_string()]),
        }),
        cli_alias::create_alias_map(
            None,
            &owned_map(hashmap! {
                "basic" => "goal",
                "nested" => "--option=advanced basic",
            })
        )
        .unwrap()
    );

    assert_eq!(
        AliasMap(hashmap! {
            "multi-nested".to_string() => AliasExpansion::Bare(vec!["deep".to_string(), "--option=advanced".to_string(), "goal".to_string()]),
            "basic".to_string() => AliasExpansion::Bare(vec!["goal".to_string()]),
            "nested".to_string() => AliasExpansion::Bare(vec!["--option=advanced".to_string(), "goal".to_string()]),
        }),
        cli_alias::create_alias_map(
            None,
            &owned_map(hashmap! {
                "multi-nested" => "deep nested",
                "basic" => "goal",
                "nested" => "--option=advanced basic",
            })
        )
        .unwrap()
    );
}

#[test]
fn test_nested_alias_with_metavar_prohibited() {
    assert_eq!(
        "Nested CLI aliases may not refer to a flag-type alias which expects a replacement parameter:\n--nested".to_string(),
        cli_alias::create_alias_map(
            None,
            &owned_map(hashmap! {
                "--nested=FOO" => "--option=$FOO",
                "root" => "goal --nested=grok",
            })
        )
        .unwrap_err()
    );
}

#[test]
fn test_alias_cycle() {
    #[track_caller]
    fn do_test_cycle(x: &str, y: &str) {
        let err_msg =
            cli_alias::create_alias_map(None, &owned_map(hashmap! { x => y, y => x,})).unwrap_err();
        assert!(err_msg.contains("CLI alias cycle detected in `[cli].alias` option:"));
        // The order in which we encounter the cycle depends on unstable HashMap iteration order,
        // so we don't know the exact error message we'll get, just that these two strings must
        // be in it.
        assert!(err_msg.contains(&format!("{} -> {}", x, y)));
        assert!(err_msg.contains(&format!("{} -> {}", y, x)));
    }

    do_test_cycle("cycle", "other_alias");
    do_test_cycle("cycle", "--other_alias");
    do_test_cycle("--cycle", "--other_alias");
}

#[test]
fn test_deep_alias_cycle() {
    let err_msg = cli_alias::create_alias_map(
        None,
        &owned_map(hashmap! {
            "xxx" => "yyy",
            "yyy" => "zzz",
            "zzz" => "www",
            "www" => "yyy",
        }),
    )
    .unwrap_err();
    assert!(err_msg.contains("CLI alias cycle detected in `[cli].alias` option:"));
    // The order in which we encounter the cycle depends on unstable HashMap iteration order,
    // so we don't know the exact error message we'll get, just that these two strings must
    // be in it.
    assert!(err_msg.contains("yyy -> zzz"));
    assert!(err_msg.contains("zzz -> www"));
    assert!(err_msg.contains("www -> yyy"));
}

#[test]
fn test_invalid_alias_name() {
    #[track_caller]
    fn do_test(alias: &str) {
        assert_eq!(
            format!(
                "Invalid alias in `[cli].alias` option: {alias}. May only contain alphanumerical \
        letters and the separators `-` and `_`. Flags can be defined using `--`. \
        A single dash is not allowed. For flags, an optional parameter may be included by \
        appending `=METAVAR` (for your choice of METAVAR) to the flag name and including \
        $METAVAR or ${{METAVAR}} in the expansion to mark where it should be inserted.",
            ),
            cli_alias::create_alias_map(None, &owned_map(hashmap! {alias => ""})).unwrap_err()
        )
    }

    do_test("dir/spec");
    do_test("file.name");
    do_test("target:name");
    do_test("-o");
    do_test("-option");
}

#[test]
fn test_banned_alias_names() {
    assert_eq!(
        "Invalid alias in `[cli].alias` option: fmt. This is already a registered goal or subsytem.",
        cli_alias::create_alias_map(
            Some(&hashmap! {"fmt".to_string() => hashset!{}}),
            &owned_map(hashmap! {"fmt" => ""}),
        )
        .unwrap_err()
    );

    assert_eq!(
        "Invalid alias in `[cli].alias` option: --keep-sandboxes. This is already a registered flag in the GLOBAL scope.",
        cli_alias::create_alias_map(
            Some(&hashmap! {"".to_string() => hashset!{"--keep-sandboxes".to_string()}}),
            &owned_map(hashmap! {"--keep-sandboxes" => ""},)
        )
        .unwrap_err()
    );

    assert_eq!(
        "Invalid alias in `[cli].alias` option: --changed-since. This is already a registered flag in the changed scope.",
        cli_alias::create_alias_map(
            Some(&hashmap! {"changed".to_string() => hashset!{"--changed-since".to_string()}}),
            &owned_map(hashmap! {"--changed-since" => ""})
        )
        .unwrap_err()
    );
}

#[test]
fn test_only_flags_are_allowed_to_have_metavars() {
    assert_eq!(
        "Invalid alias in `[cli].alias` option: grok. Only flag-type aliases may define a replacement parameter.",
        cli_alias::create_alias_map(None, &owned_map(hashmap! {"grok=FOO" => ""}),).unwrap_err()
    );
}
