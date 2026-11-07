import unittest
from core.media_playback import PlaybackGuard


class PlaybackGuardTests(unittest.TestCase):
    def test_paused_and_finished_media_never_restart(self):
        for playing, ended in [(False,False),(False,True),(True,True)]:
            g=PlaybackGuard()
            g.poll('video',5000,playing,ended,0)
            self.assertEqual(g.poll('video',5000,playing,ended,100),(False,False))

    def test_a_stalled_stream_has_bounded_recovery(self):
        g=PlaybackGuard()
        g.poll('video',5000,True,False,0)
        self.assertEqual(g.poll('video',5000,True,False,13),(False,True))
        self.assertEqual(g.poll('video',5000,True,False,14),(False,False))
        self.assertEqual(g.poll('video',5000,True,False,44),(False,True))
        self.assertEqual(g.poll('video',5000,True,False,100),(False,False))

    def test_progress_prevents_false_stall(self):
        g=PlaybackGuard()
        for i in range(90):self.assertFalse(g.poll('video',i*1000,True,False,i)[1])

    def test_a_buffering_or_stationary_picture_cannot_rewind_a_song(self):
        g=PlaybackGuard()
        self.assertFalse(g.should_sync(2000,6000,False,True,True,0))
        self.assertFalse(g.should_sync(2000,6000,True,False,True,1))
        self.assertFalse(g.should_sync(2000,6000,True,True,False,2))
        self.assertTrue(g.should_sync(2000,6000,True,True,True,3))
        self.assertFalse(g.should_sync(3000,7000,True,True,True,4))
        self.assertTrue(g.should_sync(9000,13000,True,True,True,10))

    def test_small_drift_is_left_alone(self):
        self.assertFalse(PlaybackGuard().should_sync(1000,1300,True,True,True,0))

if __name__=='__main__':unittest.main()
