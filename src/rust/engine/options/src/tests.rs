// Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::{option_id, Args, Env, OptionParser};
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
    )
    .unwrap();
    do_check(option_parser);
}

#[test]
fn test_parse_single_valued_options() {
    fn check(
        expected: i64,
        args: Vec<&'static str>,
        env: Vec<(&'static str, &'static str)>,
        config: &'static str,
    ) {
        with_setup(args, env, config, "", |option_parser| {
            let id = option_id!(["scope"], "foo");
            assert_eq!(expected, option_parser.parse_int(&id, 0).unwrap().value);
        });
    }

    check(
        3,
        vec!["--scope-foo=3"],
        vec![("PANTS_SCOPE_FOO", "2")],
        "[scope]\nfoo = 1",
    );
    check(3, vec!["--scope-foo=3"], vec![("PANTS_SCOPE_FOO", "2")], "");
    check(3, vec!["--scope-foo=3"], vec![], "[scope]\nfoo = 1");
    check(
        2,
        vec![],
        vec![("PANTS_SCOPE_FOO", "2")],
        "[scope]\nfoo = 1",
    );
    check(2, vec![], vec![("PANTS_SCOPE_FOO", "2")], "");
    check(1, vec![], vec![], "[scope]\nfoo = 1");
    check(0, vec![], vec![], "");
}

#[test]
fn test_parse_list_options() {
    fn check(
        expected: Vec<i64>,
        args: Vec<&'static str>,
        env: Vec<(&'static str, &'static str)>,
        config: &'static str,
        extra_config: &'static str,
    ) {
        with_setup(args, env, config, extra_config, |option_parser| {
            let id = option_id!(["scope"], "foo");
            assert_eq!(expected, option_parser.parse_int_list(&id, &[0]).unwrap());
        });
    }

    check(
        vec![0, 1, 2, 3, 4, 5, 6, 7],
        vec!["--scope-foo=+[5, 6, 7]"],
        vec![("PANTS_SCOPE_FOO", "+[3, 4]")],
        "[scope]\nfoo.add = [1, 2]",
        "",
    );

    check(
        vec![1, 2, 3, 4, 5, 6, 7],
        vec!["--scope-foo=+[5, 6, 7]"],
        vec![("PANTS_SCOPE_FOO", "+[3, 4]")],
        "[scope]\nfoo = [1, 2]",
        "",
    );

    check(
        vec![3, 4, 5, 6, 7],
        vec!["--scope-foo=+[5, 6, 7]"],
        vec![("PANTS_SCOPE_FOO", "[3, 4]")],
        "[scope]\nfoo.add = [1, 2]",
        "",
    );

    check(
        vec![5, 6, 7],
        vec!["--scope-foo=[5, 6, 7]"],
        vec![("PANTS_SCOPE_FOO", "+[3, 4]")],
        "[scope]\nfoo.add = [1, 2]",
        "",
    );

    check(
        vec![0, 1, 2, 11, 22, 3, 4],
        vec![],
        vec![("PANTS_SCOPE_FOO", "+[3, 4]")],
        "[scope]\nfoo = \"+[1, 2]\"",
        "[scope]\nfoo = \"+[11, 22]\"",
    );

    check(
        vec![1, 2, 3, 4],
        vec![],
        vec![("PANTS_SCOPE_FOO", "+[3, 4]")],
        "[scope]\nfoo = [1, 2]",
        "",
    );

    check(
        vec![0, 3, 4],
        vec![],
        vec![("PANTS_SCOPE_FOO", "+[3, 4]")],
        "",
        "",
    );

    check(
        vec![0, 1, 3, 4, 5, 6, 7],
        vec!["--scope-foo=+[5, 6, 7]"],
        vec![("PANTS_SCOPE_FOO", "-[2],+[3, 4]")],
        "[scope]\nfoo.add = [1, 2]",
        "",
    );

    check(vec![0, 5, 6, 7], vec!["--scope-foo=+[5, 6, 7]"], vec![], "", "");
}
