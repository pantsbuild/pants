import { Box, Grid, Typography } from '@mui/material';

import Page from 'components/Page';
import Targets from 'components/Targets';

// ----------------------------------------------------------------------

export default function ExplorerTargets() {
  return (
    <Page title="Targets">
      <Box sx={{ pb: 5 }}>
        <Typography variant="h4">
          Explore targets defined in your <code>BUILD</code> files.
        </Typography>
        <Typography variant="subtitle1">
          Use the search feature to refine the list of targets presented.
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
