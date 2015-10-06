var assert = require('assert'),
    Server = require('../dist/Server.js');

describe('Server', function() {
  it('accept parameters', function() {
    var server = new Server('0.0.0.0', 9999);
    assert.equal('0.0.0.0', server.address);
    assert.equal(9999, server.port);
  })
});
