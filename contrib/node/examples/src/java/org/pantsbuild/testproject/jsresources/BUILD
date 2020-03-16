jvm_binary(
  sources = ['JsResourcesMain.java'],
  main = 'org.pantsbuild.testproject.jsresources.JsResourcesMain',
  dependencies = [
    '3rdparty:guava',
    'contrib/node/examples/src/node/web-component-button:web-component-button-processed',
  ]
)
jvm_binary(name='jsresources-unprocessed',
  sources = ['JsResourcesMain.java'],
  main = 'org.pantsbuild.testproject.jsresources.JsResourcesMain',
  dependencies = [
    '3rdparty:guava',
    'contrib/node/examples/src/node/web-component-button:web-component-button',
  ]
)

jvm_binary(name = 'jsresources-with-dependency-artifacts',
  sources = ['JsResourcesMain.java'],
  main = 'org.pantsbuild.testproject.jsresources.JsResourcesMain',
  dependencies = [
    '3rdparty:guava',
    'contrib/node/examples/src/node/web-component-button:web-component-button-processed-with-dependency-artifacts',
  ]
)
