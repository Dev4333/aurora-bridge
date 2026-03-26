# Aurora Bridge Agent

Direct signal delivery from Aurora X to MetaTrader 5.

## User Setup (3 steps)

1. Download `AuroraBridge.exe` from Aurora X Settings
2. Run it — browser opens — log in with your Aurora X account
3. Agent auto-detects MT5 → done

## Developer Setup

```bash
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
python agent.py --setup
```

## Build .exe

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --icon=aurora.ico --name=AuroraBridge agent.py
```

Output: `dist/AuroraBridge.exe`

## CLI Options

```
python agent.py                                    # Normal start
python agent.py --setup                            # Force re-authentication
python agent.py --mt5-path "C:\...\MQL5\Files"     # Manual MT5 path
python agent.py --api-url "http://localhost:3001"   # Dev API
```
