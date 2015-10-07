var path = require('path');

var NormalConfig = {
  context: path.join(__dirname, "..", ".."),
  resolveLoader: {
    root: path.join(__dirname, "node_modules")
  },
  module: {
    loaders: [
      { test: /\.js$/, loader: "babel-loader" },
      { test: /\.css$/, loader: "style-loader!css-loader" }
    ]
  }
};

var UnitTestConfig = {
  context: path.join(__dirname, "..", ".."),
  resolveLoader: {
    root: path.join(__dirname, "node_modules")
  },
  module: {
    loaders: [
      { test: /\.js$/, loader: "babel-loader" },
      { test: /\.css$/, loader: "null-loader" }
    ]
  }
};

module.exports = {
  Normal: NormalConfig,
  UnitTest: UnitTestConfig
};
