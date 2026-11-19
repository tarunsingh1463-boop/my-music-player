# My Music Player

A Spotify-inspired desktop music player (Python, Tkinter, Pygame, Pillow, Mutagen).

## Project structure
```
my_music_player/
├── main.py            # entry point
├── ui.py              # Tkinter interface and widgets
├── music_player.py    # pygame.mixer playback engine
├── library.py         # library, playlists, likes, history (JSON)
├── requirements.txt
├── library_data.json  # created automatically on first import
└── assets/            # default_album.png is generated on first run
```

## Installation
1. Install Python 3.9+ (on Linux also: `sudo apt install python3-tk`).
2. In the project folder:
   ```
   python -m venv venv
   venv\Scripts\activate          # Windows   (macOS/Linux: source venv/bin/activate)
   pip install -r requirements.txt
   ```

## Running in VS Code
1. File → Open Folder… → select `my_music_player`.
2. Ctrl+Shift+P → "Python: Select Interpreter" → choose the `venv` one.
3. Open `main.py` and press the ▶ Run button (or run `python main.py` in the terminal).

## Importing and playing music
- Click **Import Music** (pick MP3/WAV files) or **Import Folder** (scans subfolders).
- Double-click a song, or select it and press Enter, to play. Home cards play on click.
- Right-click a song: Like, Add to playlist, Remove from playlist, Remove from library.
- **Create Playlist** is in the sidebar; right-click a playlist to delete it.
- Bottom bar: shuffle, previous, stop, play/pause, next, repeat (click again for repeat-one),
  drag the progress bar to seek, volume slider on the right. Space toggles play/pause.

## Troubleshooting
- **"No module named …"** → activate your venv and run `pip install -r requirements.txt`.
- **No module named tkinter** (Linux) → `sudo apt install python3-tk`.
- **Audio error / no sound** → check an output device is connected and not used exclusively by another app.
- **"File missing"** → the file was moved or deleted; remove it from the library and re-import.
- **Skipped on import** → only valid MP3/WAV files are supported.
- **Seeking a WAV does nothing** → some WAV files can't seek in pygame; MP3 seeks reliably.
- **Reset everything** → close the app and delete `library_data.json`.
