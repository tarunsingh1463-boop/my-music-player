"""music_player.py - Playback engine built on pygame.mixer.music.

Only one stream exists in pygame.mixer.music, so two songs can never play at once.
"""
import pygame


class MusicPlayer:
    def __init__(self):
        pygame.mixer.init()
        self.volume = 0.7
        pygame.mixer.music.set_volume(self.volume)
        self.duration = 0.0
        self.offset = 0.0      # seconds skipped by seeking
        self.playing = False   # a song is loaded and not stopped
        self.paused = False

    def play(self, path, duration, start=0.0):
        """Load and play a file. Raises pygame.error for unsupported/corrupt files."""
        pygame.mixer.music.stop()
        pygame.mixer.music.load(path)
        if start > 0:
            pygame.mixer.music.play(start=start)
        else:
            pygame.mixer.music.play()
        self.duration, self.offset = duration, start
        self.playing, self.paused = True, False

    def pause(self):
        if self.playing and not self.paused:
            pygame.mixer.music.pause()
            self.paused = True

    def resume(self):
        if self.playing and self.paused:
            pygame.mixer.music.unpause()
            self.paused = False

    def stop(self):
        pygame.mixer.music.stop()
        self.playing = self.paused = False
        self.offset = 0.0

    def seek(self, seconds):
        """Jump to a position. Returns False if the format can't seek (e.g. some WAVs)."""
        if not self.playing:
            return False
        was_paused = self.paused
        try:
            pygame.mixer.music.play(start=max(0.0, seconds))
        except pygame.error:
            return False
        self.offset = max(0.0, seconds)
        self.paused = False
        if was_paused:
            self.pause()
        return True

    def position(self):
        if not self.playing:
            return 0.0
        pos = self.offset + max(0, pygame.mixer.music.get_pos()) / 1000.0
        return min(pos, self.duration) if self.duration else pos

    def finished(self):
        """True once the current song has played to its end."""
        return self.playing and not self.paused and not pygame.mixer.music.get_busy()

    def set_volume(self, value):
        self.volume = min(1.0, max(0.0, value))
        pygame.mixer.music.set_volume(self.volume)

    def shutdown(self):
        pygame.mixer.music.stop()
        pygame.mixer.quit()
