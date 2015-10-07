var WebBuildTool = require('web-build-tool'),
    config;

if(process.env.NODE_ENV == "test") {
  config = WebBuildTool.UnitTest;

  config.entry = './test/unit.js';
  config.output = {
    path: __dirname + '/dist',
    filename: 'unit.js'
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
