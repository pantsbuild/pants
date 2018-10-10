const assert = require('assert');
const AddTwo = require('../index.js');

describe('AddTwo', function () {
  it('adds two correctly', function () {
    assert.equal(3, AddTwo.addTwo(1));
  });
});
