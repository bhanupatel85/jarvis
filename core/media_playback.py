"""Playback progress decisions, independent of Qt and signed media URLs."""
from dataclasses import dataclass


@dataclass
class Progress:
    position: int
    changed_at: float
    recovered_at: float = -1000.
    attempts: int = 0


class PlaybackGuard:
    def __init__(self, stall_seconds=12., cooldown=30., max_attempts=2):
        self.stall_seconds = stall_seconds
        self.cooldown = cooldown
        self.max_attempts = max_attempts
        self.progress = {}
        self.last_sync = -1000.

    def poll(self, key, position, playing, ended, now):
        """Return (advanced, should_recover); never recover paused/ended media."""
        old = self.progress.get(key)
        if old is None:
            self.progress[key] = Progress(position, now)
            return False, False
        advanced = position > old.position
        if not playing or ended or position != old.position:
            old.position = position
            old.changed_at = now
            return advanced, False
        if (now-old.changed_at >= self.stall_seconds
                and now-old.recovered_at >= self.cooldown
                and old.attempts < self.max_attempts):
            old.attempts += 1
            old.recovered_at = now
            old.changed_at = now
            return False, True
        return False, False

    def should_sync(self, video_position, audio_position, both_advanced,
                    both_buffered, video_seekable, now):
        if (both_advanced and both_buffered and video_seekable
                and abs(audio_position-video_position) > 600
                and now-self.last_sync >= 6):
            self.last_sync = now
            return True
        return False
