import React from 'react';
import { act, render, screen } from '@testing-library/react';
import Explorer from './Explorer';


test('renders welcome page', async () => {
  await act(async () => {
    render(<Explorer />);
  });

  const appBarTitle = screen.getByText(/Pants Build System \| Explorer/i);
  expect(appBarTitle).toBeInTheDocument();
});
