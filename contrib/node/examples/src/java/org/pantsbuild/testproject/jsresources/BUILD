jvm_binary(
  source = 'JsResourcesMain.java',
  main = 'org.pantsbuild.testproject.jsresources.JsResourcesMain',
  dependencies = [
    '3rdparty:guava',
    'contrib/node/examples/src/node/web-component-button:web-component-button-processed',
  ]
)
jvm_binary(name='jsresources-unprocessed',
  source = 'JsResourcesMain.java',
  main = 'org.pantsbuild.testproject.jsresources.JsResourcesMain',
  dependencies = [
    '3rdparty:guava',
    'contrib/node/examples/src/node/web-component-button:web-component-button',
  ]
)

jvm_binary(name = 'jsresources-with-dependency-artifacts',
  source = 'JsResourcesMain.java',
  main = 'org.pantsbuild.testproject.jsresources.JsResourcesMain',
  dependencies = [
    '3rdparty:guava',
    'contrib/node/examples/src/node/web-component-button:web-component-button-processed-with-dependency-artifacts',
  ]
)
