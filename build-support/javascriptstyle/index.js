// programmatic usage
const Linter = require('standard-engine').linter;

const opts = require('./options.js');

module.exports = new Linter(opts);
