const eslint = require('eslint');
const path = require('path');
const pkg = require('./package.json');

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
  cwd: ''     // current working directory, passed to eslint
};
