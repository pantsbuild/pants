import { Box, Grid, Typography } from '@mui/material';

import Page from 'components/Page';
import { TargetTypeDocsList } from 'components/TargetTypes';

// ----------------------------------------------------------------------

export default function ExplorerTargets() {
  return (
    <Page title="Target Types Reference Docs">
      <Box sx={{ pb: 5 }}>
        <Typography variant="h4">
          Explore target types documentation.
        </Typography>
        <Typography variant="subtitle1">
          Much to learn you still have, my young padawan.
        </Typography>
      </Box>
      <Grid container spacing={3}>
        <Grid item xs={12}>
          <TargetTypeDocsList />
        </Grid>
      </Grid>
    </Page>
  );
}
