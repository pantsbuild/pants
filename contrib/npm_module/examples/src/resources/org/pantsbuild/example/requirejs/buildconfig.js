({
  appDir: "./js",
  dir: "./min",
  baseUrl: ".",
  logLevel: 0,
  modules: [{
    name: "main",
  }],
  optimizeCss: "none",
  optimize: "uglify2",
  uglify2: {
    output: {
      beautify: false
    },
    compress: {
      sequences: false,
      global_defs: {}
    },
    warnings: true,
    mangle: true,
    useStrict: true
  }
})
