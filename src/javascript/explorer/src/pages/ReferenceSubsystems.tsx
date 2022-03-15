import { Box, Grid, Typography } from '@mui/material';

import Page from '../components/Page';
import Subsystems from '../components/docs/Subsystems';

// ----------------------------------------------------------------------

export default function ExplorerTargets() {
  return (
    <Page title="Subsystems Reference Docs">
      <Box sx={{ pb: 5 }}>
        <Typography variant="h4">
          Explore subsystems (configuration options) documentation.
        </Typography>
        <Typography variant="subtitle1">
          Much to tweak there is, young master.
        </Typography>
      </Box>
      <Grid container spacing={3}>
        <Grid item xs={12}>
          <Subsystems />
        </Grid>
      </Grid>
    </Page>
  );
}
