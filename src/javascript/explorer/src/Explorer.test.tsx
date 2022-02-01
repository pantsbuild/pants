import React from 'react';
import { render, screen } from '@testing-library/react';
import Explorer from './Explorer';

test('renders learn react link', () => {
  render(<Explorer />);
  const linkElement = screen.getByText(/learn react/i);
  expect(linkElement).toBeInTheDocument();
});
