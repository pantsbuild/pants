
import { ReactNode } from 'react';
import LinearProgress from '@mui/material/LinearProgress';
import Paper from '@mui/material/Paper';


type Props = {
  title?: string;
  children?: ReactNode;
};


export const Loading = ({ title = "Loading...", children }: Props) => {
  return (
    <Paper sx={{ m: 2, p: 2 }}>
      {title}
      <LinearProgress sx={{ m: 2 }} />
      {children}
    </Paper>
  );
};

export default Loading;
