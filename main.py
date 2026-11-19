"""main.py - Entry point for My Music Player."""
import sys


def main():
    # Check third-party libraries first so the user gets a clear message.
    try:
        import pygame, PIL, mutagen  # noqa: F401
    except ImportError as exc:
        print(f"Missing library: {exc.name}\nRun:  pip install -r requirements.txt")
        sys.exit(1)

    from ui import App
    App().run()


if __name__ == "__main__":
    main()
