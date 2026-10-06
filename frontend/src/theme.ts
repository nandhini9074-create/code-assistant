import { createTheme } from '@mui/material/styles';

/**
 * CodeLens MUI Theme
 * Dark, purple-accented Material Design theme that matches
 * the existing CodeLens brand palette.
 */
const theme = createTheme({
  palette: {
    mode: 'dark',
    primary: {
      main: 'hsl(258, 90%, 66%)',       // purple accent
      light: 'hsl(258, 90%, 76%)',
      dark: 'hsl(258, 70%, 55%)',
      contrastText: '#fff',
    },
    secondary: {
      main: 'hsl(200, 90%, 60%)',       // cyan accent-2
      contrastText: '#fff',
    },
    error: {
      main: 'hsl(0, 80%, 60%)',
    },
    warning: {
      main: 'hsl(38, 90%, 55%)',
    },
    success: {
      main: 'hsl(145, 70%, 50%)',
    },
    info: {
      main: 'hsl(200, 90%, 60%)',
    },
    background: {
      default: 'hsl(222, 20%, 6%)',
      paper: 'hsl(222, 16%, 12%)',
    },
    text: {
      primary: 'hsl(220, 20%, 95%)',
      secondary: 'hsl(220, 14%, 65%)',
      disabled: 'hsl(220, 10%, 45%)',
    },
    divider: 'hsl(222, 14%, 20%)',
  },
  typography: {
    fontFamily: "'Inter', system-ui, -apple-system, sans-serif",
    h1: { fontWeight: 700 },
    h2: { fontWeight: 700 },
    h3: { fontWeight: 700 },
    h4: { fontWeight: 600 },
    h5: { fontWeight: 600 },
    h6: { fontWeight: 600 },
    button: { textTransform: 'none', fontWeight: 600 },
  },
  shape: {
    borderRadius: 8,
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        body: {
          scrollbarWidth: 'thin',
          scrollbarColor: 'hsl(222, 14%, 20%) hsl(222, 18%, 9%)',
          '&::-webkit-scrollbar': { width: 6, height: 6 },
          '&::-webkit-scrollbar-track': { background: 'hsl(222, 18%, 9%)' },
          '&::-webkit-scrollbar-thumb': {
            background: 'hsl(222, 14%, 20%)',
            borderRadius: 3,
          },
          '&::-webkit-scrollbar-thumb:hover': {
            background: 'hsl(220, 10%, 45%)',
          },
        },
      },
    },
    MuiDrawer: {
      styleOverrides: {
        paper: {
          background: 'hsl(222, 18%, 9%)',
          borderRight: '1px solid hsl(222, 14%, 20%)',
        },
      },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          background: 'hsl(222, 18%, 9%)',
          borderBottom: '1px solid hsl(222, 14%, 20%)',
          boxShadow: 'none',
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          background: 'hsl(222, 16%, 12%)',
          border: '1px solid hsl(222, 14%, 20%)',
          boxShadow: '0 4px 16px rgba(0,0,0,.5)',
          backgroundImage: 'none',
        },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
        },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: {
          borderRadius: 8,
          fontWeight: 600,
          '&.MuiButton-containedPrimary': {
            background: 'linear-gradient(135deg, hsl(258, 90%, 66%), hsl(258, 70%, 55%))',
            '&:hover': {
              background: 'linear-gradient(135deg, hsl(258, 90%, 72%), hsl(258, 70%, 62%))',
            },
          },
        },
      },
    },
    MuiTextField: {
      defaultProps: {
        variant: 'outlined',
        size: 'small',
      },
      styleOverrides: {
        root: {
          '& .MuiOutlinedInput-root': {
            background: 'hsl(222, 20%, 6%)',
            '& fieldset': {
              borderColor: 'hsl(222, 14%, 20%)',
            },
            '&:hover fieldset': {
              borderColor: 'hsl(222, 14%, 30%)',
            },
            '&.Mui-focused fieldset': {
              borderColor: 'hsl(258, 90%, 66%)',
            },
          },
        },
      },
    },
    MuiSelect: {
      styleOverrides: {
        root: {
          background: 'hsl(222, 20%, 6%)',
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: {
          fontWeight: 600,
        },
      },
    },
    MuiTableHead: {
      styleOverrides: {
        root: {
          '& .MuiTableCell-root': {
            fontWeight: 700,
            color: 'hsl(220, 14%, 65%)',
            borderBottom: '1px solid hsl(222, 14%, 20%)',
            background: 'hsl(222, 18%, 9%)',
          },
        },
      },
    },
    MuiTableCell: {
      styleOverrides: {
        root: {
          borderBottom: '1px solid hsl(222, 14%, 17%)',
        },
      },
    },
    MuiTableRow: {
      styleOverrides: {
        root: {
          '&:hover': {
            background: 'hsl(222, 16%, 15%)',
          },
          '&:last-child td': {
            borderBottom: 0,
          },
        },
      },
    },
    MuiAlert: {
      styleOverrides: {
        root: {
          borderRadius: 8,
        },
      },
    },
    MuiLinearProgress: {
      styleOverrides: {
        root: {
          borderRadius: 4,
          height: 6,
          background: 'hsl(222, 14%, 20%)',
        },
        bar: {
          borderRadius: 4,
          background: 'linear-gradient(90deg, hsl(258, 90%, 66%), hsl(200, 90%, 60%))',
        },
      },
    },
    MuiListItemButton: {
      styleOverrides: {
        root: {
          borderRadius: 8,
          '&.Mui-selected': {
            background: 'hsla(258, 90%, 66%, 0.15)',
            '&:hover': {
              background: 'hsla(258, 90%, 66%, 0.22)',
            },
          },
          '&:hover': {
            background: 'hsl(222, 16%, 15%)',
          },
        },
      },
    },
    MuiDivider: {
      styleOverrides: {
        root: {
          borderColor: 'hsl(222, 14%, 20%)',
        },
      },
    },
    MuiDialog: {
      styleOverrides: {
        paper: {
          background: 'hsl(222, 16%, 12%)',
          border: '1px solid hsl(222, 14%, 20%)',
        },
      },
    },
    MuiTooltip: {
      styleOverrides: {
        tooltip: {
          background: 'hsl(222, 14%, 20%)',
          color: 'hsl(220, 20%, 95%)',
          fontSize: 12,
        },
      },
    },
    MuiSnackbar: {
      defaultProps: {
        anchorOrigin: { vertical: 'bottom', horizontal: 'right' },
      },
    },
  },
});

export default theme;
