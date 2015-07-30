define("constants", function () {
  var Constants = {
    styles: {
      selectedFontColor: '#333'
    },
    submitTimeout: 5000 // reduce to < 3seconds once kestrel queues are implemented.
  };
  return Constants;
});
