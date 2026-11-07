import unittest
from core.reactor_ui import motion_state, zoom_target, project_point

class ReactorMotionTests(unittest.TestCase):
    def test_real_audio_energy_and_state_are_distinct(self):
        listening=motion_state('LISTENING',False,False,.6)
        speaking=motion_state('SPEAKING',True,False,.6)
        self.assertEqual(listening.energy,.6)
        self.assertEqual(speaking.energy,.6)
        self.assertNotEqual(listening.color,speaking.color)
        self.assertGreater(speaking.speed,listening.speed)

    def test_zoom_tracks_conversation_and_respects_reduced_motion(self):
        idle=zoom_target('STANDBY',0,0)
        listening=zoom_target('LISTENING',.4,0)
        speaking=zoom_target('SPEAKING',.8,0)
        self.assertGreater(listening,idle)
        self.assertGreater(speaking,listening)
        self.assertEqual(zoom_target('SPEAKING',1,1,True),1)

    def test_perspective_depth_and_rotation(self):
        far=project_point(1,0,-1,0,0,100,0,0)
        near=project_point(1,0,1,0,0,100,0,0)
        self.assertGreater(near[0],far[0])
        rotated=project_point(1,0,1,1,0,100,0,0)
        self.assertNotEqual(rotated,near)

    def test_muted_overrides_speaking_and_audio(self):
        muted=motion_state('SPEAKING',True,True,1)
        self.assertEqual(muted.name,'MUTED')
        self.assertEqual(muted.energy,0)

    def test_no_fake_audio_in_idle(self):
        self.assertEqual(motion_state('DISCONNECTED',False,False,.9).energy,0)
        self.assertEqual(motion_state('LISTENING',False,False,0).energy,0)

if __name__=='__main__':unittest.main()
