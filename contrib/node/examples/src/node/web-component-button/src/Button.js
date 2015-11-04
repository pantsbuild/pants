var React = require('react'),
    ButtonStyles = require('./Button.css');

var Button = React.createClass({
  getInitialState: function() {
    return { clickCount: 0 };
  },

  handleClick: function() {
    this.setState({ clickCount: this.state.clickCount + 1 });
  },

  render: function() {
    return <button
      name={this.props.name}
      className='WebComponentButton'
      onClick={this.handleClick}>{this.state.clickCount} clicks!</button>
  }
});

module.exports = Button;
