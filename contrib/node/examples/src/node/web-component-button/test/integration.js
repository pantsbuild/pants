var assert = require('assert'),
    React = require('react'),
    Button = require('../src/Button.js');

describe('Button', function() {
  it('should render correctly', function() {
    assert.equal(
      '<button class="WebComponentButton">0 clicks!</button>',
      React.renderToStaticMarkup(React.createElement(Button))
    );
  })
});
