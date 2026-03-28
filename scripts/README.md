# Velluma Launch Scripts

Windows startup scripts for Velluma AI Novel Writing Assistant.

## Quick Start

### Normal Start
```
D:\qoder\Velluma\start.bat
```

### Force Mode (Kill existing processes)
```
D:\qoder\Velluma\start.bat --force
```

Use `--force` when ports are already in use by previous crashed sessions.

### Debug Mode (See all windows)
```
D:\qoder\Velluma\scripts\start-dev-debug.bat
```

## Files

| File | Description |
|------|-------------|
| `start.bat` | Main entry (project root) |
| `start-dev.ps1` | PowerShell script with port management |
| `start-dev.bat` | Batch wrapper with --force support |
| `start-dev-debug.ps1` | Debug mode (visible windows) |

## Parameters

### PowerShell Parameters
```powershell
.\scripts\start-dev.ps1 -Force          # Kill existing processes
.\scripts\start-dev.ps1 -SkipBackend    # Skip starting backend
.\scripts\start-dev.ps1 -SkipFrontend   # Skip starting frontend
.\scripts\start-dev.ps1 -ElectronOnly   # Only start Electron
```

### Batch Parameters
```batch
start.bat --force     # Kill processes on ports 8002/5175
```

## Service URLs

| Service | URL |
|---------|-----|
| Backend API | http://localhost:8002 |
| Frontend Dev | http://localhost:5175 |
| API Docs | http://localhost:8002/docs |

## Troubleshooting

### Port already in use

**Error**: `Port 5175 is in use, trying another one...`

**Solution**: Use force mode
```
start.bat --force
```

Or manually check:
```powershell
# Check what's using port 5175
netstat -ano | findstr :5175

# Kill the process
taskkill /PID <PID> /F
```

### Frontend timeout

If Frontend takes too long to start:
1. Use debug mode: `scripts\start-dev-debug.bat`
2. Check npm: `npm --version`
3. Try manually: `cd frontend && npm run dev`

### Strict Port Mode

Vite is now configured with `strictPort: true`, which means:
- ✅ It will fail fast if port 5175 is in use
- ✅ No more automatic port switching (5176, 5177...)
- ✅ Electron knows exactly which port to connect to

If you need the old behavior, edit `frontend/vite.config.js` and remove `strictPort: true`.

## Process Management

Scripts automatically manage:
- Python backend processes
- Node.js (Vite dev server)
- Node.js (Electron)

All processes are stopped when you:
- Press Ctrl+C
- Close the launcher window
