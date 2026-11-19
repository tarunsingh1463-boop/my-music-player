"""library.py - Music library, playlists, likes and history (saved to JSON)."""
import hashlib
import json
import os
from pathlib import Path

from mutagen import File as MutagenFile

SUPPORTED_EXTENSIONS = (".mp3", ".wav")
DATA_FILE = Path(__file__).resolve().parent / "library_data.json"


def _tag(tags, key):
    """Safely read the first text value of an ID3 frame."""
    try:
        frame = tags.get(key) if tags else None
        return str(frame.text[0]).strip() if frame is not None and frame.text else ""
    except Exception:
        return ""


class Library:
    def __init__(self, data_file=DATA_FILE):
        self.data_file = Path(data_file)
        self.songs = {}       # id -> {id, path, title, artist, duration, plays}
        self.playlists = {}   # name -> [song ids]
        self.liked = []       # [song ids]
        self.recent = []      # [song ids], newest first
        self._load()

    # ---------- persistence ----------
    def _load(self):
        try:
            data = json.loads(self.data_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self.songs = data.get("songs", {})
        self.playlists = data.get("playlists", {})
        self.liked = data.get("liked", [])
        self.recent = data.get("recent", [])

    def save(self):
        data = {"songs": self.songs, "playlists": self.playlists,
                "liked": self.liked, "recent": self.recent}
        tmp = self.data_file.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            os.replace(tmp, self.data_file)
        except OSError:
            pass

    # ---------- songs ----------
    def get(self, sid):
        return self.songs.get(sid)

    def import_file(self, path):
        """Add a file. Returns (song, is_new). Raises ValueError on bad files."""
        path = os.path.abspath(path)
        if not path.lower().endswith(SUPPORTED_EXTENSIONS):
            raise ValueError("unsupported format (use MP3 or WAV)")
        if not os.path.isfile(path):
            raise ValueError("file not found")
        sid = hashlib.md5(path.lower().encode()).hexdigest()[:12]
        if sid in self.songs:
            return self.songs[sid], False
        try:
            audio = MutagenFile(path)
        except Exception as exc:
            raise ValueError(f"unreadable audio file ({exc})")
        if audio is None or getattr(audio, "info", None) is None:
            raise ValueError("unreadable audio file")
        song = {
            "id": sid, "path": path,
            "title": _tag(audio.tags, "TIT2") or Path(path).stem,
            "artist": _tag(audio.tags, "TPE1") or "Unknown Artist",
            "duration": float(getattr(audio.info, "length", 0) or 0),
            "plays": 0,
        }
        self.songs[sid] = song
        self.save()
        return song, True

    def artwork(self, path):
        """Return embedded cover-art bytes, or None."""
        try:
            audio = MutagenFile(path)
            if audio is not None and audio.tags:
                for key in audio.tags.keys():
                    if key.startswith("APIC"):
                        return audio.tags[key].data
        except Exception:
            pass
        return None

    def remove_song(self, sid):
        self.songs.pop(sid, None)
        self.liked = [i for i in self.liked if i != sid]
        self.recent = [i for i in self.recent if i != sid]
        for name in self.playlists:
            self.playlists[name] = [i for i in self.playlists[name] if i != sid]
        self.save()

    def all_ids(self):
        return list(self.songs)

    def search(self, query):
        q = query.strip().lower()
        if not q:
            return []
        return [i for i, s in self.songs.items()
                if q in s["title"].lower() or q in s["artist"].lower()]

    def popular(self, n):
        ids = sorted(self.songs, key=lambda i: -self.songs[i].get("plays", 0))
        return ids[:n]

    # ---------- history / likes ----------
    def add_recent(self, sid):
        self.recent = [sid] + [i for i in self.recent if i != sid]
        self.recent = self.recent[:30]
        if sid in self.songs:
            self.songs[sid]["plays"] = self.songs[sid].get("plays", 0) + 1
        self.save()

    def is_liked(self, sid):
        return sid in self.liked

    def toggle_like(self, sid):
        if sid in self.liked:
            self.liked.remove(sid)
        else:
            self.liked.insert(0, sid)
        self.save()
        return sid in self.liked

    # ---------- playlists ----------
    def create_playlist(self, name):
        name = name.strip()
        if not name or name in self.playlists:
            return False
        self.playlists[name] = []
        self.save()
        return True

    def delete_playlist(self, name):
        self.playlists.pop(name, None)
        self.save()

    def add_to_playlist(self, name, sid):
        if name in self.playlists and sid not in self.playlists[name]:
            self.playlists[name].append(sid)
            self.save()

    def remove_from_playlist(self, name, sid):
        if name in self.playlists and sid in self.playlists[name]:
            self.playlists[name].remove(sid)
            self.save()
