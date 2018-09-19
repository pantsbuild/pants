var assert = require('assert'),
    AddTwo = require('../index.js');

describe('AddTwo', function() {
  it('adds two correctly', function() {
    assert.equal(3, AddTwo.addTwo(1));
  })
});
