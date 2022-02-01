import { Box, Grid, Container, Typography } from '@mui/material';

import Page from '../components/Page';
import Target from '../components/Targets/Target';

// ----------------------------------------------------------------------

export default function ExplorerHome() {
  return (
    <Page title="Explorer | Pants Build System">
      <Container maxWidth="xl">
        <Box sx={{ pb: 5 }}>
          <Typography variant="h4">Hi, Welcome to your Pantsbuild Explorer UI.</Typography>
        </Box>
        <Grid container spacing={3}>
          <Grid item xs={12} sm={6} md={3}>
            Info.
          </Grid>
          <Grid item xs={12} sm={6} md={3}>
            <Target />
          </Grid>
        </Grid>
      </Container>
    </Page>
  );
}
