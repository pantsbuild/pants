var assert = require('assert'),
    Button = require('../src/Button.js');

describe('Button', function() {
  it('should load', function() {
    assert.equal('Button', Button.displayName);
  })
});
