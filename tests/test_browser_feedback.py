import asyncio
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch, AsyncMock
from types import SimpleNamespace

from core import browser_feedback as feedback, personal_browser as personal
from core.uia_worker import execute


class BrowserFeedbackTests(unittest.TestCase):
    def test_no_capture_of_another_application(self):
        with patch.object(feedback, 'foreground_browser', return_value=None):
            self.assertIsNone(feedback.capture('inspect'))

    def test_inline_frame_delivered_to_the_same_session(self):
        session = Mock(send_client_content=AsyncMock())
        asyncio.run(feedback.deliver(session, [(b'jpeg', 'image/jpeg', 'observed')]))
        call = session.send_client_content.call_args.kwargs
        self.assertEqual(call['turns']['parts'][1]['inline_data']['data'], 'anBlZw==')
        self.assertFalse(call['turn_complete'])

    def test_image_context_precedes_tool_completion_without_interrupting(self):
        events = []
        async def image(**kwargs):
            self.assertFalse(kwargs['turn_complete'])
            events.append('image')
        async def response(**kwargs):
            events.append('tool_response')
        session = Mock(send_client_content=image, send_tool_response=response)
        asyncio.run(feedback.respond(session, [], [(b'jpeg','image/jpeg','evidence')]))
        self.assertEqual(events, ['image','tool_response'])

    def test_image_send_failure_still_returns_the_tool_result(self):
        session = Mock(send_client_content=AsyncMock(side_effect=RuntimeError('failed')),
                       send_tool_response=AsyncMock())
        result = SimpleNamespace(response={'result':'status=observed'})
        asyncio.run(feedback.respond(session, [result], [(b'jpeg','image/jpeg','evidence')]))
        session.send_tool_response.assert_awaited_once()
        self.assertIn('BROWSER_FRAME_SEND_FAILED', result.response['result'])

    def test_frame_discarded_if_user_switches_windows_during_capture(self):
        screen = Mock()
        screen.monitors = [dict(left=0, top=0, width=100, height=100)]
        screen.grab.return_value = SimpleNamespace(size=(10,10), rgb=bytes(300))
        context = Mock()
        context.__enter__ = Mock(return_value=screen)
        context.__exit__ = Mock(return_value=False)
        with patch.object(feedback, 'foreground_browser', side_effect=[(42,(0,0,10,10)),None]), patch('mss.mss',return_value=context):
            self.assertIsNone(feedback.capture('inspect'))

    def test_value_verification_does_not_return_value(self):
        record = dict(id='field', name='Email', role='Edit', visible=True, enabled=True, password=False)
        target = Mock()
        target.iface_value.CurrentValue = 'sample@example.test'
        with patch('core.uia_worker.snapshot', return_value=([record], {'field':target})):
            result = execute(dict(action='verify_value', element_id='field', text='sample@example.test'), Mock(), lambda:42)
        self.assertEqual(result['status'], 'value_verified')
        self.assertNotIn('sample', json.dumps(result))

    def test_wrong_value_is_not_success(self):
        record = dict(id='field', name='Email', role='Edit', visible=True, enabled=True, password=False)
        target = Mock()
        target.iface_value.CurrentValue = 'wrong'
        with patch('core.uia_worker.snapshot', return_value=([record], {'field':target})):
            result = execute(dict(action='verify_value', element_id='field', text='expected'), Mock(), lambda:42)
        self.assertEqual(result['status'], 'value_mismatch')

    def test_password_never_read_back(self):
        record = dict(id='field', name='Password', role='Edit', visible=True, enabled=True, password=True)
        target = Mock()
        with patch('core.uia_worker.snapshot', return_value=([record], {'field':target})):
            result = execute(dict(action='verify_value', element_id='field', text='private'), Mock(), lambda:42)
        self.assertEqual(result['status'], 'private_field')
        self.assertNotIn('iface_value', [call[0] for call in target.mock_calls])

    def test_visual_field_focus_must_contain_clicked_point(self):
        record = dict(id='field', role='Edit', bounds=[100,100,300,140])
        with patch('core.uia_worker.snapshot', return_value=([record], {'field':Mock()})):
            wrong = execute(dict(action='focused_field', x=10, y=10), Mock(), lambda:42)
            right = execute(dict(action='focused_field', x=120, y=120), Mock(), lambda:42)
        self.assertEqual(wrong['status'], 'focus_unverified')
        self.assertEqual(right['element_id'], 'field')

    def test_typing_stops_when_focus_is_unverified(self):
        cc = Mock()
        with patch.object(personal, 'click_observed', side_effect=personal.InteractionError('focus_lost','lost')), patch.object(personal,'paste_text') as paste:
            with self.assertRaises(personal.InteractionError):
                personal.type_observed(cc, 'Email', 'sample')
            paste.assert_not_called()

    def test_verified_typing_checks_actual_target_without_echoing(self):
        cc = Mock()
        with patch.object(personal, 'click_observed', return_value={'element_id':'field'}), patch.object(personal,'paste_text'), patch.object(personal,'_uia', return_value={'status':'value_verified'}) as uia:
            result = personal.type_observed(cc, 'Email', 'sample')
        self.assertEqual(result['status'], 'value_verified')
        self.assertEqual(uia.call_args.kwargs['element_id'], 'field')

    def test_windows_scroll_uses_full_wheel_notches(self):
        from actions import computer_control as cc
        with patch.object(personal, 'focus_browser', return_value=42), patch.object(cc, '_scroll') as scroll:
            personal.control({'action':'scroll', 'direction':'down', 'amount':500}, 'chrome', str, Mock())
        scroll.assert_called_once_with('down', 600)


class BrowserDispatcherTests(unittest.IsolatedAsyncioTestCase):
    async def test_browser_frame_is_attached_to_the_correct_call(self):
        import main
        from google.genai import types
        jarvis = main.JarvisLive.__new__(main.JarvisLive)
        jarvis.ui = Mock(muted=True)
        jarvis._action_registry = Mock()
        jarvis._action_registry.has.return_value = True
        jarvis._action_registry.run.return_value = 'status=unverified'
        jarvis._action_registry.scheduling.return_value = None
        jarvis._plugin_registry = Mock()
        jarvis._plugin_registry.scheduling.return_value = None
        jarvis._browser_evidence = {}
        frame = (b'jpeg', 'image/jpeg', 'test evidence')
        with patch('core.browser_feedback.capture', return_value=frame):
            result = await jarvis._execute_tool_impl(types.FunctionCall(
                id='browser-test', name='browser_control', args={'action':'inspect'}))
        self.assertEqual(jarvis._browser_evidence['browser-test'], frame)
        self.assertIn('BROWSER_FRAME_ATTACHED', result.response['result'])


if __name__ == '__main__':
    unittest.main()
