import React from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import Drawer from '@mui/material/Drawer';
import Box from '@mui/material/Box';
import List from '@mui/material/List';
import ListItemButton from '@mui/material/ListItemButton';
import ListItemIcon from '@mui/material/ListItemIcon';
import ListItemText from '@mui/material/ListItemText';
import Typography from '@mui/material/Typography';
import Divider from '@mui/material/Divider';
import Tooltip from '@mui/material/Tooltip';
import SearchIcon from '@mui/icons-material/Search';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import UploadFileIcon from '@mui/icons-material/UploadFile';
import WorkHistoryIcon from '@mui/icons-material/WorkHistory';
import MonitorHeartIcon from '@mui/icons-material/MonitorHeart';
import CodeIcon from '@mui/icons-material/Code';
import HealthIndicator from './HealthIndicator';

interface NavItemDef {
  to: string;
  icon: React.ReactNode;
  label: string;
  id: string;
}

interface Props {
  width: number;
}

const navSections: { label: string; items: NavItemDef[] }[] = [
  {
    label: 'Explore',
    items: [
      { to: '/',       icon: <SearchIcon fontSize="small" />,      label: 'Search',       id: 'nav-search' },
    ],
  },
  {
    label: 'Manage',
    items: [
      { to: '/repositories', icon: <AccountTreeIcon fontSize="small" />, label: 'Repositories', id: 'nav-repositories' },
      { to: '/upload',       icon: <UploadFileIcon fontSize="small" />,  label: 'Upload ZIP',   id: 'nav-upload' },
      { to: '/jobs',         icon: <WorkHistoryIcon fontSize="small" />, label: 'Jobs',         id: 'nav-jobs' },
    ],
  },
  {
    label: 'System',
    items: [
      { to: '/health', icon: <MonitorHeartIcon fontSize="small" />, label: 'Health', id: 'nav-health' },
    ],
  },
];

const Sidebar: React.FC<Props> = ({ width }) => {
  const location = useLocation();

  return (
    <Drawer
      variant="permanent"
      sx={{
        width,
        flexShrink: 0,
        '& .MuiDrawer-paper': {
          width,
          boxSizing: 'border-box',
          display: 'flex',
          flexDirection: 'column',
        },
      }}
    >
      {/* Logo */}
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 1.5,
          px: 2.5,
          py: 2.5,
          borderBottom: '1px solid',
          borderColor: 'divider',
        }}
      >
        <Box
          sx={{
            width: 36,
            height: 36,
            borderRadius: 2,
            background: 'linear-gradient(135deg, hsl(258,90%,66%), hsl(258,70%,55%))',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
          }}
        >
          <CodeIcon sx={{ color: '#fff', fontSize: 20 }} />
        </Box>
        <Box>
          <Typography variant="subtitle1" sx={{ fontWeight: 700, lineHeight: 1.2 }}>
            CodeLens
          </Typography>
          <Typography variant="caption" color="text.secondary" sx={{ lineHeight: 1.2 }}>
            AI Code Intelligence
          </Typography>
        </Box>
      </Box>

      {/* Navigation */}
      <Box sx={{ flex: 1, overflowY: 'auto', py: 1 }}>
        {navSections.map((section) => (
          <Box key={section.label}>
            <Typography
              variant="caption"
              color="text.disabled"
              sx={{ px: 2.5, pt: 2, pb: 0.5, display: 'block', letterSpacing: '0.08em', textTransform: 'uppercase', fontWeight: 700 }}
            >
              {section.label}
            </Typography>
            <List dense disablePadding sx={{ px: 1 }}>
              {section.items.map((item) => {
                const isActive = location.pathname === item.to;
                return (
                  <Tooltip key={item.to} title="" placement="right">
                    <ListItemButton
                      component={NavLink}
                      to={item.to}
                      id={item.id}
                      selected={isActive}
                      aria-current={isActive ? 'page' : undefined}
                      sx={{
                        borderRadius: 2,
                        mb: 0.25,
                        color: isActive ? 'primary.main' : 'text.secondary',
                        '& .MuiListItemIcon-root': {
                          color: isActive ? 'primary.main' : 'text.secondary',
                          minWidth: 34,
                        },
                      }}
                    >
                      <ListItemIcon>{item.icon}</ListItemIcon>
                      <ListItemText
                        primary={item.label}
                        sx={{
                          '& .MuiListItemText-primary': {
                            fontSize: 14,
                            fontWeight: isActive ? 600 : 400,
                          },
                        }}
                      />
                      {isActive && (
                        <Box
                          sx={{
                            width: 3,
                            height: 20,
                            borderRadius: 4,
                            bgcolor: 'primary.main',
                            ml: 0.5,
                          }}
                        />
                      )}
                    </ListItemButton>
                  </Tooltip>
                );
              })}
            </List>
          </Box>
        ))}
      </Box>

      {/* Footer */}
      <Divider />
      <Box sx={{ px: 2.5, py: 1.5 }}>
        <HealthIndicator compact />
      </Box>
    </Drawer>
  );
};

export default Sidebar;
