// Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::{
    option_id, Args, DictEdit, DictEditAction, Env, ListEdit, ListEditAction, OptionParser, Source,
    Val,
};
use maplit::hashmap;
use std::collections::HashMap;
use std::fs::File;
use std::io::Write;
use tempfile::TempDir;

fn with_setup(
    args: Vec<&'static str>,
    env: Vec<(&'static str, &'static str)>,
    config: &'static str,
    extra_config: &'static str,
    do_check: impl Fn(OptionParser),
) {
    let buildroot = TempDir::new().unwrap();
    let config_path = buildroot.path().join("pants.toml");
    File::create(&config_path)
        .unwrap()
        .write_all(config.as_bytes())
        .unwrap();
    let extra_config_path = buildroot.path().join("pants_extra.toml");
    File::create(&extra_config_path)
        .unwrap()
        .write_all(extra_config.as_bytes())
        .unwrap();
    let config_file_arg = vec![format!(
        "--pants-config-files={}",
        extra_config_path.to_str().unwrap()
    )];

    let option_parser = OptionParser::new(
        Args {
            args: config_file_arg
                .into_iter()
                .chain(args.into_iter().map(str::to_string))
                .collect(),
        },
        Env {
            env: env
                .into_iter()
                .map(|(k, v)| (k.to_owned(), v.to_owned()))
                .collect::<HashMap<_, _>>(),
        },
        Some(vec![
            config_path.to_str().unwrap(),
            extra_config_path.to_str().unwrap(),
        ]),
        false,
        true,
    )
    .unwrap();
    do_check(option_parser);
}

#[test]
fn test_parse_single_valued_options() {
    fn check(
        expected: i64,
        expected_derivation: Vec<(Source, i64)>,
        args: Vec<&'static str>,
        env: Vec<(&'static str, &'static str)>,
        config: &'static str,
    ) {
        with_setup(args, env, config, "", |option_parser| {
            let id = option_id!(["scope"], "foo");
            let option_value = option_parser.parse_int(&id, 0).unwrap();
            assert_eq!(expected, option_value.value);
            assert_eq!(expected_derivation, option_value.derivation.unwrap());
        });
    }

    check(
        3,
        vec![
            (Source::Default, 0),
            (Source::Config, 1),
            (Source::Env, 2),
            (Source::Flag, 3),
        ],
        vec!["--scope-foo=3"],
        vec![("PANTS_SCOPE_FOO", "2")],
        "[scope]\nfoo = 1",
    );
    check(
        3,
        vec![(Source::Default, 0), (Source::Env, 2), (Source::Flag, 3)],
        vec!["--scope-foo=3"],
        vec![("PANTS_SCOPE_FOO", "2")],
        "",
    );
    check(
        3,
        vec![(Source::Default, 0), (Source::Config, 1), (Source::Flag, 3)],
        vec!["--scope-foo=3"],
        vec![],
        "[scope]\nfoo = 1",
    );
    check(
        2,
        vec![(Source::Default, 0), (Source::Config, 1), (Source::Env, 2)],
        vec![],
        vec![("PANTS_SCOPE_FOO", "2")],
        "[scope]\nfoo = 1",
    );
    check(
        2,
        vec![(Source::Default, 0), (Source::Env, 2)],
        vec![],
        vec![("PANTS_SCOPE_FOO", "2")],
        "",
    );
    check(
        1,
        vec![(Source::Default, 0), (Source::Config, 1)],
        vec![],
        vec![],
        "[scope]\nfoo = 1",
    );
    check(0, vec![(Source::Default, 0)], vec![], vec![], "");
}

#[test]
fn test_parse_list_options() {
    fn check(
        expected: Vec<i64>,
        expected_derivation: Vec<(Source, Vec<ListEdit<i64>>)>,
        args: Vec<&'static str>,
        env: Vec<(&'static str, &'static str)>,
        config: &'static str,
        extra_config: &'static str,
    ) {
        with_setup(args, env, config, extra_config, |option_parser| {
            let id = option_id!(["scope"], "foo");
            let option_value = option_parser.parse_int_list(&id, &[0]).unwrap();
            assert_eq!(expected, option_value.value);
            assert_eq!(expected_derivation, option_value.derivation.unwrap());
        });
    }

    fn replace(items: Vec<i64>) -> ListEdit<i64> {
        ListEdit {
            action: ListEditAction::Replace,
            items,
        }
    }

    fn add(items: Vec<i64>) -> ListEdit<i64> {
        ListEdit {
            action: ListEditAction::Add,
            items,
        }
    }

    fn remove(items: Vec<i64>) -> ListEdit<i64> {
        ListEdit {
            action: ListEditAction::Remove,
            items,
        }
    }

    check(
        vec![0, 1, 2, 3, 4, 5, 6, 7],
        vec![
            (Source::Default, vec![replace(vec![0])]),
            (Source::Config, vec![add(vec![1, 2])]),
            (Source::Env, vec![add(vec![3, 4])]),
            (Source::Flag, vec![add(vec![5, 6, 7])]),
        ],
        vec!["--scope-foo=+[5, 6, 7]"],
        vec![("PANTS_SCOPE_FOO", "+[3, 4]")],
        "[scope]\nfoo.add = [1, 2]",
        "",
    );

    check(
        vec![1, 2, 3, 4, 5, 6, 7],
        vec![
            (Source::Default, vec![replace(vec![0])]),
            (Source::Config, vec![replace(vec![1, 2])]),
            (Source::Env, vec![add(vec![3, 4])]),
            (Source::Flag, vec![add(vec![5, 6, 7])]),
        ],
        vec!["--scope-foo=+[5, 6, 7]"],
        vec![("PANTS_SCOPE_FOO", "+[3, 4]")],
        "[scope]\nfoo = [1, 2]",
        "",
    );

    check(
        vec![3, 4, 5, 6, 7],
        vec![
            (Source::Default, vec![replace(vec![0])]),
            (Source::Config, vec![add(vec![1, 2])]),
            (Source::Env, vec![replace(vec![3, 4])]),
            (Source::Flag, vec![add(vec![5, 6, 7])]),
        ],
        vec!["--scope-foo=+[5, 6, 7]"],
        vec![("PANTS_SCOPE_FOO", "[3, 4]")],
        "[scope]\nfoo.add = [1, 2]",
        "",
    );

    check(
        vec![5, 6, 7],
        vec![
            (Source::Default, vec![replace(vec![0])]),
            (Source::Config, vec![add(vec![1, 2])]),
            (Source::Env, vec![add(vec![3, 4])]),
            (Source::Flag, vec![replace(vec![5, 6, 7])]),
        ],
        vec!["--scope-foo=[5, 6, 7]"],
        vec![("PANTS_SCOPE_FOO", "+[3, 4]")],
        "[scope]\nfoo.add = [1, 2]",
        "",
    );

    check(
        vec![0, 1, 2, 11, 22, 3, 4],
        vec![
            (Source::Default, vec![replace(vec![0])]),
            (Source::Config, vec![add(vec![1, 2]), add(vec![11, 22])]),
            (Source::Env, vec![add(vec![3, 4])]),
        ],
        vec![],
        vec![("PANTS_SCOPE_FOO", "+[3, 4]")],
        "[scope]\nfoo = \"+[1, 2]\"",
        "[scope]\nfoo = \"+[11, 22]\"",
    );

    check(
        vec![1, 3, 4],
        vec![
            (Source::Default, vec![replace(vec![0])]),
            (
                Source::Config,
                vec![replace(vec![1, 2]), remove(vec![2, 4])],
            ),
            (Source::Env, vec![add(vec![3, 4])]),
        ],
        vec![],
        vec![("PANTS_SCOPE_FOO", "+[3, 4]")],
        "[scope]\nfoo = [1, 2]",
        "[scope]\nfoo = '-[2, 4]'", // 2 should be removed, but not 4, since env has precedence.
    );

    check(
        vec![0, 3, 4],
        vec![
            (Source::Default, vec![replace(vec![0])]),
            (Source::Env, vec![add(vec![3, 4])]),
        ],
        vec![],
        vec![("PANTS_SCOPE_FOO", "+[3, 4]")],
        "",
        "",
    );

    check(
        vec![0, 1, 3, 4, 5, 6, 7],
        vec![
            (Source::Default, vec![replace(vec![0])]),
            (Source::Config, vec![add(vec![1, 2])]),
            (Source::Env, vec![remove(vec![2]), add(vec![3, 4])]),
            (Source::Flag, vec![add(vec![5, 6, 7])]),
        ],
        vec!["--scope-foo=+[5, 6, 7]"],
        vec![("PANTS_SCOPE_FOO", "-[2],+[3, 4]")],
        "[scope]\nfoo.add = [1, 2]",
        "",
    );

    check(
        vec![0, 5, 6, 7],
        vec![
            (Source::Default, vec![replace(vec![0])]),
            (Source::Flag, vec![add(vec![5, 6, 7])]),
        ],
        vec!["--scope-foo=+[5, 6, 7]"],
        vec![],
        "",
        "",
    );
}

#[test]
fn test_parse_dict_options() {
    fn with_owned_keys(dict: HashMap<&str, Val>) -> HashMap<String, Val> {
        dict.into_iter().map(|(k, v)| (k.to_string(), v)).collect()
    }

    fn check(
        expected: HashMap<&str, Val>,
        expected_derivation: Vec<(Source, Vec<DictEdit>)>,
        args: Vec<&'static str>,
        env: Vec<(&'static str, &'static str)>,
        config: &'static str,
        extra_config: &'static str,
    ) {
        let expected = with_owned_keys(expected);
        with_setup(args, env, config, extra_config, |option_parser| {
            let id = option_id!(["scope"], "foo");
            let default = HashMap::from([
                ("key1".to_string(), Val::Int(1)),
                ("key2".to_string(), Val::String("val2".to_string())),
            ]);
            let option_value = option_parser.parse_dict(&id, default).unwrap();
            assert_eq!(expected, option_value.value);
            assert_eq!(expected_derivation, option_value.derivation.unwrap())
        });
    }

    fn replace(items: HashMap<&str, Val>) -> DictEdit {
        DictEdit {
            action: DictEditAction::Replace,
            items: with_owned_keys(items),
        }
    }

    fn add(items: HashMap<&str, Val>) -> DictEdit {
        DictEdit {
            action: DictEditAction::Add,
            items: with_owned_keys(items),
        }
    }

    let default_derivation = (
        Source::Default,
        vec![replace(
            hashmap! {"key1" => Val::Int(1), "key2" => Val::String("val2".to_string())},
        )],
    );

    check(
        hashmap! {
            "key1" => Val::Int(1),
            "key2" => Val::String("val2".to_string()),
            "key3" => Val::Int(3),
            "key4" => Val::Float(4.0),
            "key5" => Val::Bool(true),
            "key6" => Val::Int(6),
        },
        vec![
            default_derivation.clone(),
            (
                Source::Config,
                vec![
                    add(hashmap! {"key5" => Val::Bool(true)}),
                    add(hashmap! {"key6" => Val::Int(6)}),
                ],
            ),
            (Source::Env, vec![add(hashmap! {"key4" => Val::Float(4.0)})]),
            (Source::Flag, vec![add(hashmap! {"key3" => Val::Int(3)})]),
        ],
        vec!["--scope-foo=+{'key3': 3}"],
        vec![("PANTS_SCOPE_FOO", "+{'key4': 4.0}")],
        "[scope]\nfoo = \"+{ 'key5': true }\"",
        "[scope]\nfoo = \"+{ 'key6': 6 }\"",
    );

    check(
        hashmap! {
            "key3" => Val::Int(3),
            "key4" => Val::Float(4.0),
            "key6" => Val::Int(6),
        },
        vec![
            default_derivation.clone(),
            (
                Source::Config,
                vec![
                    add(hashmap! {"key5" => Val::Bool(true)}),
                    replace(hashmap! {"key6" => Val::Int(6)}),
                ],
            ),
            (Source::Env, vec![add(hashmap! {"key4" => Val::Float(4.0)})]),
            (Source::Flag, vec![add(hashmap! {"key3" => Val::Int(3)})]),
        ],
        vec!["--scope-foo=+{'key3': 3}"],
        vec![("PANTS_SCOPE_FOO", "+{'key4': 4.0}")],
        "[scope]\nfoo = \"+{ 'key5': true }\"",
        "[scope.foo]\nkey6 = 6",
    );

    check(
        hashmap! {
            "key3" => Val::Int(3),
            "key4" => Val::Float(4.0),
        },
        vec![
            default_derivation.clone(),
            (
                Source::Config,
                vec![
                    add(hashmap! {"key5" => Val::Bool(true)}),
                    replace(hashmap! {"key6" => Val::Int(6)}),
                ],
            ),
            (
                Source::Env,
                vec![replace(hashmap! {"key4" => Val::Float(4.0)})],
            ),
            (Source::Flag, vec![add(hashmap! {"key3" => Val::Int(3)})]),
        ],
        vec!["--scope-foo=+{'key3': 3}"],
        vec![("PANTS_SCOPE_FOO", "{'key4': 4.0}")],
        "[scope]\nfoo = \"+{ 'key5': true }\"",
        "[scope.foo]\nkey6 = 6",
    );

    check(
        hashmap! {
            "key3" => Val::Int(3),
        },
        vec![
            default_derivation.clone(),
            (
                Source::Config,
                vec![
                    add(hashmap! {"key5" => Val::Bool(true)}),
                    replace(hashmap! {"key6" => Val::Int(6)}),
                ],
            ),
            (
                Source::Env,
                vec![replace(hashmap! {"key4" => Val::Float(4.0)})],
            ),
            (
                Source::Flag,
                vec![replace(hashmap! {"key3" => Val::Int(3)})],
            ),
        ],
        vec!["--scope-foo={'key3': 3}"],
        vec![("PANTS_SCOPE_FOO", "{'key4': 4.0}")],
        "[scope]\nfoo = \"+{ 'key5': true }\"",
        "[scope.foo]\nkey6 = 6",
    );

    check(
        hashmap! {
            "key1" => Val::Int(1),
            "key2" => Val::String("val2".to_string()),
        },
        vec![default_derivation],
        vec![],
        vec![],
        "",
        "",
    );
}
