import unittest
from core.audio_lifecycle import playback_drained
class PlaybackDrainTests(unittest.TestCase):
 def test_missing_model_event_recovers_after_real_playback(self):
  self.assertTrue(playback_drained(10,11,.2,True))
 def test_gap_and_queued_audio_do_not_reopen_mic(self):
  self.assertFalse(playback_drained(10,10.2,.2,True))
  self.assertFalse(playback_drained(10,12,.2,False))
 def test_no_playback_is_not_a_completed_response(self):
  self.assertFalse(playback_drained(None,100,.2,True))
if __name__=='__main__':unittest.main()
