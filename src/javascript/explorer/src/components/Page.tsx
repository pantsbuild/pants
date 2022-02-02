import * as React from 'react';
import { Helmet } from 'react-helmet-async';
import Box from '@mui/material/Box';
import Container from '@mui/material/Container';
import Link from '@mui/material/Link';
import Toolbar from '@mui/material/Toolbar';
import Typography from '@mui/material/Typography';

// ----------------------------------------------------------------------

type Props = {
  children: React.ReactNode;
  title?: string;
};

export default React.forwardRef(({ children, title = '', ...other }: Props, ref) => (
  <Box
    ref={ref}
    component="main"
    sx={{
      backgroundColor: (theme) =>
        theme.palette.mode === 'light'
        ? theme.palette.grey[100]
        : theme.palette.grey[900],
      flexGrow: 1,
      height: '100vh',
      overflow: 'auto',
    }}
    {...other}
  >
    <Toolbar /> {/* Empty toolbar for padding, so page content doesn't "hide" beneath the nav bar. */}
    <Container sx={{ mt: 4, mb: 4 }} maxWidth={false}>
      <Helmet>
        <title>{title} | Explorer</title>
      </Helmet>
      {children}
      <Copyright sx={{ pt: 4 }} />
    </Container>
  </Box>
));


function Copyright(props: any) {
  return (
    <Typography variant="body2" color="text.secondary" align="center" {...props}>
      {'Copyright © '}
      <Link color="inherit" href="https://www.pantsbuild.org">
        Pants Build System
      </Link>{' '}
      {new Date().getFullYear()}
      {'.'}
    </Typography>
  );
}
