import React, { useState, useCallback } from 'react';
import { Button } from '@pants-example/shared-components';
import { add, formatDate, createResult, isValidEmail } from '@pants-example/shared-utils';
import type { Config, User, Status } from '@pants-example/common-types';

interface AppProps {
  config: Config;
}

export function App({ config }: AppProps) {
  const [count, setCount] = useState(0);
  const [email, setEmail] = useState('');
  const [status, setStatus] = useState<Status>('pending');

  const handleIncrement = useCallback(() => {
    setCount(current => add(current, 1));
  }, []);

  const handleEmailChange = useCallback((event: React.ChangeEvent<HTMLInputElement>) => {
    setEmail(event.target.value);
    setStatus(isValidEmail(event.target.value) ? 'success' : 'error');
  }, []);

  const currentDate = formatDate(new Date());
  
  // Simulate user data
  const user: User = {
    id: '1',
    name: 'Demo User',
    email: 'demo@example.com',
    createdAt: new Date(),
  };

  const result = createResult('success', user);

  return (
    <div style={{ padding: '20px', fontFamily: 'Arial, sans-serif' }}>
      <h1>TypeScript Monorepo Example</h1>
      
      <section>
        <h2>Configuration</h2>
        <p>API URL: {config.apiUrl}</p>
        <p>Timeout: {config.timeout}ms</p>
        <p>Current Date: {currentDate}</p>
      </section>

      <section>
        <h2>Counter Demo</h2>
        <p>Count: {count}</p>
        <Button onClick={handleIncrement} variant="primary">
          Increment
        </Button>
      </section>

      <section>
        <h2>Email Validation Demo</h2>
        <input
          type="email"
          value={email}
          onChange={handleEmailChange}
          placeholder="Enter your email"
          style={{ 
            padding: '8px', 
            marginRight: '10px',
            border: `2px solid ${status === 'error' ? 'red' : status === 'success' ? 'green' : 'gray'}`
          }}
        />
        <Button 
          variant={status === 'success' ? 'primary' : 'secondary'}
          disabled={status !== 'success'}
          status={status}
        >
          Submit
        </Button>
      </section>

      <section>
        <h2>User Data</h2>
        {result.status === 'success' && result.data && (
          <div>
            <p>Name: {result.data.name}</p>
            <p>Email: {result.data.email}</p>
            <p>ID: {result.data.id}</p>
          </div>
        )}
      </section>
    </div>
  );
}