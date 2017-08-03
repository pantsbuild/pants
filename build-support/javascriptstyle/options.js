const eslint = require('eslint');
const path = require('path');
const pkg = require('./package.json');
const exclude = require('./exclude.js');

// Option configuration for standard-engine
// See https://github.com/standard/standard-engine for more details.
module.exports = {
  cmd: 'javascriptstyle', // should match the "bin" key in your package.json
  version: pkg.version,
  homepage: pkg.homepage,
  bugs: pkg.bugs.url,
  tagline: 'Pants JavaScript Standard Style',
  eslint: eslint,
  eslintConfig: {
    configFile: path.join(__dirname, '.eslintrc')
  },
  parseOpts: function (opts, packageOpts, rootDir) {
    // Ignore the excluded files
    opts.ignore.push.apply(opts.ignore, exclude.files)
    return opts
  },
  cwd: ''     // current working directory, passed to eslint
};
