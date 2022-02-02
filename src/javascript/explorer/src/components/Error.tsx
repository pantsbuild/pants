
import { ReactNode } from 'react';
import Alert from '@mui/material/Alert';
import AlertTitle from '@mui/material/AlertTitle';
import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';


type Props = {
  title?: string;
  error: string;
  children?: ReactNode;
};


export const Error = ({ title = "Error", error, children }: Props) => {
  return (
    <Paper sx={{ m: 2, p: 2 }}>
      <Alert severity="error">
        <AlertTitle>{title}</AlertTitle>
        <Typography>{error}</Typography>
        {children}
      </Alert>
    </Paper>
  );
};

export default Error;
