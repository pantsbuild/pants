var assert = require('assert'),
    Project = require('../src/Project.js');

describe('Project', function() {
  it('should load', function() {
    assert.equal('Project', Project.displayName);
  })
});
