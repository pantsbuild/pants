var WebBuildTool = require('web-build-tool'),
    config;

if(process.env.NODE_ENV == "test") {
  config = WebBuildTool.UnitTest;

  config.entry = {
    'unit': './test/unit.js',
    'integration': './test/integration.js'
  };
  config.output = {
    path: __dirname + '/dist/test',
    filename: '[name].js'
  };
} else {
  config = WebBuildTool.Normal;

  config.entry = './src/Button.js';
  config.output = {
    path: __dirname + '/dist',
    filename: 'Button.js'
  };
}

module.exports = config;
