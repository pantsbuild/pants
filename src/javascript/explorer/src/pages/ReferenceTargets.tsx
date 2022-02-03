import { Box, Grid, Typography } from '@mui/material';

import Page from '../components/Page';
import TargetTypes from '../components/docs/Targets';

// ----------------------------------------------------------------------

export default function ExplorerTargets() {
  return (
    <Page title="Targets Reference Docs">
      <Box sx={{ pb: 5 }}>
        <Typography variant="h4">
          Explore targets documentation.
        </Typography>
        <Typography variant="subtitle1">
          Much to learn you still have, my young padawan.
        </Typography>
      </Box>
      <Grid container spacing={3}>
        <Grid item xs={12}>
          <TargetTypes />
        </Grid>
      </Grid>
    </Page>
  );
}
