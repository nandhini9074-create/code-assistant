import React from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import MonitorHeartIcon from '@mui/icons-material/MonitorHeart';
import HealthIndicator from '../components/HealthIndicator';

const HealthPage: React.FC = () => {
  return (
    <Box sx={{ px: { xs: 2, md: 4 }, py: 3 }}>
      <Typography variant="h4" fontWeight={800} gutterBottom>
        System Health
      </Typography>
      <Typography variant="body2" color="text.secondary" mb={3}>
        Live status of all backend services.
      </Typography>

      <Card sx={{ maxWidth: 480 }}>
        <CardContent>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2.5 }}>
            <MonitorHeartIcon sx={{ color: 'primary.main' }} />
            <Typography variant="subtitle1" fontWeight={700}>
              Service Status
            </Typography>
          </Box>
          <HealthIndicator />
        </CardContent>
      </Card>
    </Box>
  );
};

export default HealthPage;
