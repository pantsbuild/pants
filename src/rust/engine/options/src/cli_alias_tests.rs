// Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::cli_alias;
use crate::cli_alias::AliasMap;
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

fn owned_map_vec(x: HashMap<&str, Vec<&str>>) -> HashMap<String, Vec<String>> {
    x.into_iter()
        .map(|(k, v)| (k.to_string(), owned_vec(v)))
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
fn test_nested_alias() {
    assert_eq!(
        AliasMap(owned_map_vec(hashmap! {
            "basic" => vec!["goal"],
            "nested" => vec!["--option=advanced", "goal"],
        })),
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
        AliasMap(owned_map_vec(hashmap! {
            "multi-nested" => vec!["deep", "--option=advanced", "goal"],
            "basic" => vec!["goal"],
            "nested" => vec!["--option=advanced", "goal"],
        })),
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
fn test_alias_cycle() {
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
    fn do_test(alias: &str) {
        assert_eq!(
            format!(
                "Invalid alias in `[cli].alias` option: {}. May only contain alphanumerical \
        letters and the separators `-` and `_`. Flags can be defined using `--`. \
        A single dash is not allowed.",
                alias
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
            Some(&hashmap!{"fmt".to_string() => hashset!{}}),
            &owned_map(hashmap!{"fmt" => ""}),
        ).unwrap_err()
    );

    assert_eq!(
        "Invalid alias in `[cli].alias` option: --keep-sandboxes. This is already a registered flag in the GLOBAL scope.",
        cli_alias::create_alias_map(
            Some(&hashmap!{"".to_string() => hashset!{"--keep-sandboxes".to_string()}}),
            &owned_map(hashmap!{"--keep-sandboxes" => ""},
        )
    ).unwrap_err()
        );

    assert_eq!(
        "Invalid alias in `[cli].alias` option: --changed-since. This is already a registered flag in the changed scope.",
        cli_alias::create_alias_map(
            Some(&hashmap!{"changed".to_string() => hashset!{"--changed-since".to_string()}}),
            &owned_map(hashmap!{"--changed-since" => ""})
        ).unwrap_err()
    );
}
