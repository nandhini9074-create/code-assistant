import { createTheme } from '@mui/material/styles';

const theme = createTheme({
  palette: {
    mode: 'dark',
    primary: {
      main: 'hsl(258, 90%, 66%)',
      light: 'hsl(258, 90%, 76%)',
      dark: 'hsl(258, 70%, 52%)',
      contrastText: '#ffffff',
    },
    secondary: {
      main: 'hsl(200, 90%, 62%)',
      contrastText: '#ffffff',
    },
    error: {
      main: 'hsl(350, 85%, 60%)',
    },
    warning: {
      main: 'hsl(38, 92%, 58%)',
    },
    success: {
      main: 'hsl(152, 70%, 52%)',
    },
    info: {
      main: 'hsl(200, 90%, 60%)',
    },
    background: {
      default: 'hsl(222, 24%, 8%)',
      paper: 'hsl(222, 18%, 12%)',
    },
    text: {
      primary: 'hsl(220, 24%, 96%)',
      secondary: 'hsl(220, 16%, 72%)',
      disabled: 'hsl(220, 12%, 52%)',
    },
    divider: 'hsl(222, 14%, 22%)',
  },
  typography: {
    fontFamily: "'Inter', 'Segoe UI', sans-serif",
    h1: { fontWeight: 800, letterSpacing: '-0.04em' },
    h2: { fontWeight: 800, letterSpacing: '-0.04em' },
    h3: { fontWeight: 800, letterSpacing: '-0.03em' },
    h4: { fontWeight: 800, letterSpacing: '-0.03em' },
    h5: { fontWeight: 700, letterSpacing: '-0.02em' },
    h6: { fontWeight: 700, letterSpacing: '-0.02em' },
    button: { textTransform: 'none', fontWeight: 700, letterSpacing: '0.01em' },
    body1: { lineHeight: 1.6 },
    body2: { lineHeight: 1.6 },
  },
  shape: {
    borderRadius: 12,
  },
  shadows: [
    'none',
    '0 1px 2px rgba(10, 15, 30, 0.24)',
    '0 3px 8px rgba(10, 15, 30, 0.24)',
    '0 8px 24px rgba(10, 15, 30, 0.28)',
    '0 12px 32px rgba(10, 15, 30, 0.32)',
    '0 18px 48px rgba(10, 15, 30, 0.34)',
    '0 22px 56px rgba(10, 15, 30, 0.38)',
    '0 26px 72px rgba(10, 15, 30, 0.42)',
    '0 30px 80px rgba(10, 15, 30, 0.5)',
    '0 36px 96px rgba(10, 15, 30, 0.6)',
    '0 40px 110px rgba(10, 15, 30, 0.68)',
    '0 50px 140px rgba(10, 15, 30, 0.72)',
    '0 60px 180px rgba(10, 15, 30, 0.8)',
    '0 72px 200px rgba(10, 15, 30, 0.9)',
    '0 82px 220px rgba(10, 15, 30, 0.96)',
    '0 90px 240px rgba(10, 15, 30, 1)',
    '0 100px 260px rgba(10, 15, 30, 1)',
    '0 110px 280px rgba(10, 15, 30, 1)',
    '0 120px 300px rgba(10, 15, 30, 1)',
    '0 130px 320px rgba(10, 15, 30, 1)',
    '0 140px 340px rgba(10, 15, 30, 1)',
    '0 150px 360px rgba(10, 15, 30, 1)',
    '0 160px 380px rgba(10, 15, 30, 1)',
    '0 170px 400px rgba(10, 15, 30, 1)',
    '0 180px 440px rgba(10, 15, 30, 1)',
  ],
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        ':root': {
          colorScheme: 'dark',
        },
        html: {
          scrollBehavior: 'smooth',
        },
        body: {
          margin: 0,
          background:
            'radial-gradient(circle at top left, rgba(122, 92, 255, 0.12), transparent 30%), radial-gradient(circle at top right, rgba(35, 160, 255, 0.12), transparent 22%), hsl(222, 24%, 8%)',
          color: 'hsl(220, 24%, 96%)',
          scrollbarWidth: 'thin',
          scrollbarColor: 'hsl(222, 14%, 20%) hsl(222, 18%, 9%)',
          '&::-webkit-scrollbar': { width: 8, height: 8 },
          '&::-webkit-scrollbar-track': { background: 'hsl(222, 18%, 9%)' },
          '&::-webkit-scrollbar-thumb': {
            background: 'hsl(222, 14%, 24%)',
            borderRadius: 8,
          },
          '&::-webkit-scrollbar-thumb:hover': {
            background: 'hsl(222, 14%, 30%)',
          },
        },
      },
    },
    MuiDrawer: {
      styleOverrides: {
        paper: {
          background: 'linear-gradient(180deg, hsl(222, 18%, 9%) 0%, hsl(222, 18%, 10%) 100%)',
          borderRight: '1px solid hsl(222, 14%, 20%)',
          boxShadow: '0 18px 54px rgba(0, 0, 0, 0.42)',
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          background: 'linear-gradient(180deg, rgba(20,24,38,0.92), rgba(15,18,27,0.96))',
          border: '1px solid hsl(222, 14%, 20%)',
          boxShadow: '0 10px 24px rgba(0,0,0,0.18)',
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
      defaultProps: {
        disableElevation: true,
      },
      styleOverrides: {
        root: {
          borderRadius: 10,
          fontWeight: 700,
          minHeight: 42,
          paddingInline: 16,
          transition: 'transform 0.18s ease, box-shadow 0.18s ease, filter 0.18s ease',
          '&.MuiButton-containedPrimary': {
            background: 'linear-gradient(135deg, hsl(258, 90%, 66%), hsl(258, 70%, 56%))',
            boxShadow: '0 12px 26px rgba(122, 92, 255, 0.32)',
            '&:hover': {
              background: 'linear-gradient(135deg, hsl(258, 90%, 70%), hsl(258, 70%, 60%))',
            },
          },
          '&:hover': {
            transform: 'translateY(-1px)',
            filter: 'brightness(1.02)',
          },
          '&:active': {
            transform: 'translateY(0)',
          },
        },
        sizeSmall: {
          minHeight: 36,
          paddingInline: 12,
        },
        outlined: {
          borderColor: 'hsl(222, 14%, 24%)',
          '&:hover': {
            borderColor: 'hsl(222, 14%, 32%)',
            backgroundColor: 'rgba(255, 255, 255, 0.02)',
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
            background: 'rgba(5, 8, 18, 0.72)',
            borderRadius: 10,
            transition: 'all 0.2s ease',
            '& fieldset': {
              borderColor: 'hsl(222, 14%, 24%)',
            },
            '&:hover fieldset': {
              borderColor: 'hsl(222, 14%, 36%)',
            },
            '&.Mui-focused fieldset': {
              borderColor: 'hsl(258, 90%, 66%)',
              boxShadow: '0 0 0 3px rgba(122, 92, 255, 0.14)',
            },
          },
          '& .MuiInputLabel-root': {
            color: 'hsl(220, 16%, 72%)',
          },
        },
      },
    },
    MuiSelect: {
      styleOverrides: {
        root: {
          background: 'rgba(5, 8, 18, 0.72)',
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: {
          fontWeight: 700,
          borderRadius: 999,
        },
      },
    },
    MuiTableHead: {
      styleOverrides: {
        root: {
          '& .MuiTableCell-root': {
            fontWeight: 700,
            color: 'hsl(220, 14%, 70%)',
            borderBottom: '1px solid hsl(222, 14%, 20%)',
            background: 'rgba(10, 14, 22, 0.9)',
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
            background: 'rgba(255, 255, 255, 0.02)',
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
          borderRadius: 12,
          boxShadow: '0 6px 18px rgba(0,0,0,0.1)',
        },
      },
    },
    MuiLinearProgress: {
      styleOverrides: {
        root: {
          borderRadius: 999,
          height: 8,
          background: 'hsl(222, 14%, 24%)',
          overflow: 'hidden',
        },
        bar: {
          borderRadius: 999,
          background: 'linear-gradient(90deg, hsl(258, 90%, 66%), hsl(200, 90%, 60%))',
        },
      },
    },
    MuiListItemButton: {
      styleOverrides: {
        root: {
          borderRadius: 10,
          transition: 'all 0.18s ease',
          '&.Mui-selected': {
            background: 'linear-gradient(90deg, rgba(122, 92, 255, 0.18), rgba(122, 92, 255, 0.1))',
            boxShadow: 'inset 0 0 0 1px rgba(122, 92, 255, 0.08)',
            '&:hover': {
              background: 'linear-gradient(90deg, rgba(122, 92, 255, 0.22), rgba(122, 92, 255, 0.12))',
            },
          },
          '&:hover': {
            background: 'rgba(255, 255, 255, 0.03)',
          },
        },
      },
    },
    MuiDialog: {
      styleOverrides: {
        paper: {
          borderRadius: 16,
          border: '1px solid hsl(222, 14%, 22%)',
          boxShadow: '0 18px 52px rgba(0,0,0,0.36)',
        },
      },
    },
  },
});

export default theme;
