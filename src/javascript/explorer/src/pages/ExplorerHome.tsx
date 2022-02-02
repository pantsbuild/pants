import { Box, Grid, Typography } from '@mui/material';

import Page from '../components/Page';
import Targets from '../components/Targets';

// ----------------------------------------------------------------------

export default function ExplorerHome() {
  return (
    <Page title="Dashboard">
      <Box sx={{ pb: 5 }}>
        <Typography variant="h4">
          Hi, and Welcome to your very own Pantsbuild Explorer UI.
        </Typography>
        <Typography variant="body2">
          Here you can get to know your repository better, by inspecting targets, dependencies, documentation and more.
        </Typography>
      </Box>
      <Grid container spacing={3}>
        <Grid item xs={12}>
          <Targets />
        </Grid>
      </Grid>
    </Page>
  );
}
