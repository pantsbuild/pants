# Setting up JavaScript Style Checker

1. Download the javascriptstyle directory from https://github.com/pantsbuild/pants/tree/master/build-support/javascriptstyle
into your local pants_supportdir directory.
2. Configure pants.ini
3. Add new rules
4. Add plugins to extend beyond the default ruleset
5. Blacklisting

## Configuring pants.ini

	[lint.javascriptstyle]
	javascriptstyle_dir: %(pants_supportdir)s/javascriptstyle
	skip: False
	fail_slow: False

	[fmt.javascriptstyle]
	javascriptstyle_dir: %(pants_supportdir)s/javascriptstyle
	skip: False
	fail_slow: False


## Adding new rules

Add new rules to the .eslintrc file under the "rules" section.
A full list of eslint rules can be found at http://eslint.org/docs/rules

For plugins, you will need to append the plugin name followed by a '/'.

    "react/jsx-indent": [2, 2]


## Adding new plugins

New plugins will need to be installed in the package.json and added to the .eslintrc

To add react plugin to package.json:

    yarn add eslint-plugin-react

To add react plugin to .eslintrc:

    "plugins": [
      "react"
    ],


## Blacklisting

You can blacklist files to be excluded from the style checker by listing them in exclude.js.

The blacklist supports glob/rglob through the use of \*/\*\* syntax. See default.

By default the paths:

- node_modules/\*\*
- *\.min.js
- bundle.js
- coverage/\*\*
- hidden files/folders (beginning with .)

and all patterns in a project's root .gitignore file are automatically ignored.
