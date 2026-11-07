"""Operate the user's visible browser without creating an automation profile."""
import platform
import json
import contextvars
from core import accessibility, diagnostics
import time
from urllib.parse import quote_plus
from core import outcome
from core.maps_navigation import is_maps_url

_active = 'chrome'
_target_window = contextvars.ContextVar('personal_browser_window', default=0)
_EXECUTABLES = {'chrome': 'chrome.exe', 'edge': 'msedge.exe', 'firefox': 'firefox.exe',
                'brave': 'brave.exe', 'opera': 'opera.exe', 'operagx': 'opera.exe',
                'vivaldi': 'vivaldi.exe'}


def focus_browser(browser):
    """Only report focus when Windows confirms the foreground process identity."""
    if platform.system() != 'Windows' or browser not in _EXECUTABLES:
        return False
    import ctypes
    from ctypes import wintypes
    import psutil
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    def matches(hwnd):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        try:
            process = psutil.Process(pid.value)
            if process.name().lower() != _EXECUTABLES[browser]:
                return False
            command = ' '.join(process.cmdline()).lower()
            return '.jarvis_profiles' not in command and '--enable-automation' not in command
        except (psutil.Error, OSError):
            return False
    current = user32.GetForegroundWindow()
    if current and matches(current):
        return int(current)
    windows = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    @callback_type
    def visit(hwnd, extra):
        if user32.IsWindowVisible(hwnd) and matches(hwnd):
            windows.append(hwnd)
        return True
    user32.EnumWindows(visit, 0)
    for hwnd in windows:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.15)
        if user32.GetForegroundWindow() == hwnd:
            return int(hwnd)
    return False


def paste_text(cc, text):
    """Paste Unicode, restore clipboard contents, and never echo credentials."""
    cc._require_pyautogui()
    if not cc._require_pyperclip():
        raise RuntimeError('Clipboard support is needed for personal-browser typing')
    previous = cc.pyperclip.paste()
    try:
        cc.pyperclip.copy(str(text))
        cc.pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.15)
    finally:
        cc.pyperclip.copy(previous)


def read_url(cc):
    if not cc._require_pyperclip():
        return ''
    previous = cc.pyperclip.paste()
    try:
        cc.pyperclip.copy('')
        cc._hotkey('ctrl', 'l')
        cc._hotkey('ctrl', 'c')
        time.sleep(0.15)
        return str(cc.pyperclip.paste()).strip()
    finally:
        cc._press('escape')
        cc.pyperclip.copy(previous)


class InteractionError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _uia(action, **params):
    result = accessibility.request(action, hwnd=_target_window.get(), **params)
    diagnostics.record(action, result.get('status', 'unknown'), backend='uia',
                       attempted=result.get('attempted', False))
    return result


def click_observed(cc, description, *, editing=False, element_id='', snapshot='', dialog_only=False):
    result = _uia('focus' if editing else 'click', description=description,
                  element_id=element_id, snapshot=snapshot, dialog_only=dialog_only)
    status = result.get('status')
    if result.get('attempted'):
        if editing and status != 'focused':
            raise InteractionError('focus_unverified', 'Field focus was not verified. No text was entered; inspect the page before retrying.')
        if status in {'unknown', 'timeout', 'unverified'}:
            raise InteractionError(status, 'The input outcome is unknown. Inspect the screen before retrying.')
        return result
    if status not in {'not_found', 'unavailable'} or element_id:
        raise InteractionError(status, 'Control selection failed: ' + str(status) + '. Inspect the current controls before retrying.')
    if dialog_only:
        # Never fall back to an unscoped "Close" that could close Chrome itself.
        description = 'Close or Dismiss button inside the visible popup dialog, NOT the browser window close button'
    coords = cc._screen_find(description)
    if not coords:
        raise InteractionError('not_found', 'The requested control was not found by accessibility or visual recognition. Inspect the screen.')
    width, height = cc.pyautogui.size()
    x, y = coords
    if not (0 <= x < width and 0 <= y < height):
        raise InteractionError('invalid_coordinates', 'Visual recognition returned coordinates outside the display.')
    if _target_window.get():
        import ctypes
        from ctypes import wintypes
        ctypes.windll.user32.GetForegroundWindow.restype = wintypes.HWND
        if int(ctypes.windll.user32.GetForegroundWindow() or 0) != _target_window.get():
            raise InteractionError('focus_lost', 'The browser lost focus while locating the control. No click was sent.')
    cc._click(x, y)
    diagnostics.record('click', 'unverified', backend='vision', attempted=True)
    if editing:
        # A visual icon/field may have no accessible label. Verify the actual
        # keyboard focus after the visual click instead of guessing its label.
        verified = _uia('focused_field', x=x, y=y)
        if verified.get('status') != 'focused':
            raise InteractionError('focus_unverified', 'Could not verify the field focus. No text was entered. Inspect the page and name the field.')
        return verified
    return {'status':'unverified', 'attempted':True}


def type_observed(cc, description, text, *, element_id='', snapshot='', clear_first=True):
    focused = click_observed(cc, description, editing=True, element_id=element_id, snapshot=snapshot)
    if clear_first:
        cc._hotkey('ctrl', 'a')
    paste_text(cc, text)
    target_id = focused.get('element_id', '')
    if not target_id:
        return {'status': 'value_unavailable'}
    return _uia('verify_value', element_id=target_id, text=text, clear_first=clear_first)


def control(params, browser, normalize_url, open_native):
    global _active
    from actions import computer_control as cc
    from actions.browser_control import _ALIASES, _SEARCH_ENGINES
    selected = browser or _active
    selected = _ALIASES.get(selected, selected)
    action = params.get('action', '').strip().lower()
    if action == 'switch':
        selected = browser or params.get('target', '')
        selected = _ALIASES.get(selected.lower().strip(), selected.lower().strip())
    if selected not in _EXECUTABLES:
        return outcome.failed('browser_control', 'That personal browser is not supported on Windows')
    _active = selected
    if params.get('incognito'):
        return outcome.failed('browser_control', 'Private mode would not use your personal signed-in session')
    if action == 'list_browsers':
        return outcome.done('browser_control', browser=selected, mode='personal', verified=True)
    if action == 'close_all':
        return outcome.failed('browser_control', 'Name the personal browser to close; other personal windows were left alone')
    try:
        focused = focus_browser(selected)
        _target_window.set(int(focused or 0))
        if not focused:
            if action == 'search':
                query = str(params.get('query', '')).strip()
                if not query:
                    return outcome.failed('browser_control', 'Provide a search query')
                base = _SEARCH_ENGINES.get(params.get('engine', 'google'), _SEARCH_ENGINES['google'])
                result = open_native(base + quote_plus(query), selected)
                return outcome.unverified('browser_control', 'Search navigation requested. Inspect the browser evidence before claiming results loaded.', browser=selected) if result.startswith('Opened') else result
            if action == 'map_search':
                query = str(params.get('query', '')).strip()
                if not query:
                    return outcome.failed('browser_control', 'Provide a place to search')
                return open_native('https://www.google.com/maps/search/?api=1&query=' + quote_plus(query), selected)
            if action in {'go_to', 'new_tab'}:
                url = normalize_url(params.get('url', ''))
                result = open_native(url, selected)
                if result.startswith('Opened'):
                    return outcome.unverified('browser_control', 'Opened the requested address in your personal browser; inspect the screen to verify', browser=selected)
                return result
            diagnostics.record(action, 'focus_lost', backend='native')
            return outcome.failed('browser_control', 'Could not focus your personal browser. Open it first; no input or separate browser was launched.')
        if action == 'switch':
            return outcome.done('browser_control', browser=selected, mode='personal', focused=True, verified=True)
        if action in {'observe', 'inspect', 'inspect_form', 'get_text'}:
            observed = _uia('inspect')
            if observed.get('status') == 'observed':
                if action == 'inspect_form':
                    observed = {**observed, 'controls': [item for item in observed.get('controls', [])
                                if item.get('role') in {'Edit', 'ComboBox', 'CheckBox', 'RadioButton', 'Button'}]}
                return outcome.untrusted('personal-browser-controls', json.dumps(observed, ensure_ascii=False))
            return outcome.unverified('browser_control', 'Accessibility could not read controls (' + str(observed.get('status')) + '). Use the attached screenshot to identify the page or popup; do not invent controls.')
        if action == 'get_url':
            url = read_url(cc)
            return outcome.done('browser_control', url=url, verified=True) if url else outcome.failed('browser_control', 'Could not read the active address')
        if action in {'search', 'map_search'}:
            query = str(params.get('query', '')).strip()
            if not query:
                return outcome.failed('browser_control', 'Provide a search query')
            scope = params.get('scope', 'auto')
            current = read_url(cc)
            if action == 'map_search' or scope == 'maps' or (scope == 'auto' and is_maps_url(current)):
                if not is_maps_url(current):
                    cc._hotkey('ctrl', 'l')
                    paste_text(cc, 'https://www.google.com/maps/search/?api=1&query=' + quote_plus(query))
                    cc._press('enter')
                    return outcome.unverified('browser_control', 'Opened a Maps place search in your personal tab; inspect the place result before claiming it was found')
                click_observed(cc, 'Search Google Maps', editing=True)
                cc._hotkey('ctrl', 'a')
                paste_text(cc, query)
                cc._press('enter')
                return outcome.unverified('browser_control', 'Place search entered in your personal Maps tab; check the screen for the resulting place')
            if scope == 'auto' and not current:
                return outcome.failed('browser_control', 'Could not read the active site; inspect the screen before choosing Maps or web search')
            base = _SEARCH_ENGINES.get(params.get('engine', 'google'), _SEARCH_ENGINES['google'])
            params = {**params, 'url': base + quote_plus(query)}
            action = 'go_to'
        if action in {'go_to', 'new_tab'}:
            url = normalize_url(params.get('url', ''))
            cc._hotkey('ctrl', 't' if action == 'new_tab' else 'l')
            paste_text(cc, url)
            cc._press('enter')
        elif action in {'smart_click', 'click', 'open_result', 'zoom', 'dismiss_popup'}:
            if action == 'dismiss_popup':
                description = params.get('description') or 'close popup'
            elif action == 'open_result':
                index = params.get('index', 1)
                if not isinstance(index, int) or not 1 <= index <= 10:
                    raise ValueError('Choose a visible result from 1 to 10')
                description = f'the title link of organic search result number {index}, excluding advertisements'
            elif action == 'zoom':
                if not is_maps_url(read_url(cc)):
                    return outcome.failed('browser_control', 'Map zoom requires the active Google Maps tab; use page_zoom for webpage text')
                direction = params.get('direction', 'in')
                if direction not in {'in', 'out'}:
                    raise ValueError('Zoom direction must be in or out')
                description = f'the map Zoom {direction} button'
            else:
                description = params.get('description') or params.get('text')
                if not description and not params.get('element_id'):
                    raise ValueError('Describe the visible control or use an observed element_id')
            steps = params.get('steps', 1) if action == 'zoom' else 1
            if not isinstance(steps, int) or isinstance(steps, bool) or not 1 <= steps <= 5:
                raise ValueError('Use one to five zoom steps')
            operation = {}
            for _ in range(steps):
                operation = click_observed(cc, description or '', element_id=params.get('element_id', ''),
                    snapshot=params.get('snapshot', ''), dialog_only=action == 'dismiss_popup')
                if operation.get('status') == 'unchanged':
                    break  # Do not keep clicking an unresponsive or blocked control.
            if action == 'dismiss_popup' and operation.get('status') == 'dialog_dismissed':
                return outcome.done('browser_control', popup_dismissed=True, verified=True)
            observed = operation.get('controls')
            if observed is not None:
                evidence = {key: operation[key] for key in ('status', 'hwnd', 'snapshot', 'controls') if key in operation}
                return ('status=observed action=browser_control input_attempted=true task_verified=false\n'
                    'Read the observed controls and attached browser image to decide whether the requested state was reached. '
                    'A UI change alone does not prove task completion.\n' +
                    outcome.untrusted('personal-browser-controls', json.dumps(evidence)))
        elif action == 'fill_form':
            fields = params.get('fields', [])
            if isinstance(fields, dict):
                fields = [{'label': label, 'value': value} for label, value in fields.items()]
            if not isinstance(fields, list) or not 1 <= len(fields) <= 20:
                raise ValueError('Provide between one and twenty named fields')
            if any(not isinstance(field, dict) or not str(field.get('label', '')).strip()
                   or not isinstance(field.get('value'), str) for field in fields):
                raise ValueError('Each field needs a visible label and string value')
            completed = 0
            verified_count = 0
            for field in fields:
                try:
                    checked = type_observed(cc, field['label'], field['value'])
                    completed += 1
                    verified_count += checked.get('status') == 'value_verified'
                    if checked.get('status') in {'value_mismatch', 'focus_lost'}:
                        return outcome.unverified('browser_control', f'Input attempted for {completed} fields, but the last field did not verify. Stopped without submitting; inspect before retrying.')
                except Exception:
                    return outcome.failed('browser_control', f'Filled {completed} of {len(fields)} fields; stopped because the next field could not be focused. Values are private. Inspect before retrying.')
            return outcome.unverified('browser_control', f'Input sent to {completed} fields; {verified_count} field values verified. No form submitted. Inspect the page; login has not been verified.')
        elif action in {'select_option', 'set_checked'}:
            description = str(params.get('description', '')).strip()
            if not description and not params.get('element_id'):
                raise ValueError('Name the dropdown or checkbox, or supply an observed control ID')
            if action == 'select_option' and not str(params.get('option', '')).strip():
                raise ValueError('Specify the visible option text')
            if action == 'set_checked' and not isinstance(params.get('checked'), bool):
                raise ValueError('Specify checked=true or false')
            result = _uia(action, description=description, element_id=params.get('element_id', ''),
                          snapshot=params.get('snapshot', ''), option=params.get('option', ''),
                          checked=params.get('checked'))
            if result.get('status') in {'selected', 'checked'}:
                return outcome.done('browser_control', control_updated=True, verified=True)
            if result.get('status') == 'options_observed':
                return ('status=observed action=browser_control task_verified=false\n'
                    'The dropdown is open. Use inspect and smart_click on the unique requested option.\n' +
                    outcome.untrusted('personal-browser-controls', json.dumps(result)))
            return outcome.failed('browser_control', 'The requested control state was not verified (' + str(result.get('status')) + '). Inspect before retrying.')
        elif action == 'find_on_page':
            query = str(params.get('query', '')).strip()
            if not query:
                raise ValueError('Provide text to find on the page')
            cc._hotkey('ctrl', 'f')
            paste_text(cc, query)
        elif action == 'switch_tab':
            index = params.get('index', 1)
            if not isinstance(index, int) or isinstance(index, bool) or not 1 <= index <= 8:
                raise ValueError('Use a tab number from one to eight')
            cc._hotkey('ctrl', str(index))
        elif action == 'pan':
            if not is_maps_url(read_url(cc)):
                return outcome.failed('browser_control', 'Map panning requires the active Google Maps tab')
            direction = params.get('direction', 'up')
            if direction not in {'up', 'down', 'left', 'right'}:
                raise ValueError('Use up, down, left or right')
            steps = params.get('steps', 1)
            if not isinstance(steps, int) or isinstance(steps, bool) or not 1 <= steps <= 5:
                raise ValueError('Use one to five pan steps')
            focused_map = _uia('focus_surface', description='Map')
            if focused_map.get('status') != 'focused':
                return outcome.failed('browser_control', 'The map surface could not be focused; no arrow keys were sent. Inspect the page.')
            for _ in range(steps):
                cc._press(direction)
        elif action == 'page_zoom':
            direction = params.get('direction', 'in')
            if direction not in {'in', 'out', 'reset'}:
                raise ValueError('Use in, out or reset')
            cc._hotkey('ctrl', {'in': '+', 'out': '-', 'reset': '0'}[direction])
        elif action in {'next_tab', 'previous_tab'}:
            cc._hotkey('ctrl', *(['shift', 'tab'] if action == 'previous_tab' else ['tab']))
        elif action in {'type', 'smart_type'}:
            description = params.get('description')
            if description or params.get('element_id'):
                operation = type_observed(cc, description or '', params.get('text', ''),
                    element_id=params.get('element_id', ''), snapshot=params.get('snapshot', ''),
                    clear_first=params.get('clear_first', True))
            else:
                raise ValueError('Name the visible field or supply its observed element_id before typing')
            if operation.get('status') == 'value_verified':
                return outcome.done('browser_control', field_value_verified=True, submitted=False)
            return outcome.unverified('browser_control', 'Field input attempted; verification=' +
                str(operation.get('status')) + '. No form submitted. Inspect before retrying; never repeat private values aloud.')
        elif action == 'screenshot':
            return cc._screenshot(params.get('path'))
        elif action == 'close':
            return outcome.failed('browser_control', 'Use close_tab for the active tab; closing all personal browser windows needs an explicit desktop request')
        elif action == 'press':
            key = str(params.get('key', 'enter')).lower()
            if key not in {'enter', 'escape', 'tab', 'backspace', 'delete', 'up', 'down', 'left', 'right', 'space', 'f5'}:
                raise ValueError('Use a single browser navigation key')
            cc._press(key)
        elif action == 'wait':
            seconds = float(params.get('seconds', 1))
            if not 0.1 <= seconds <= 5:
                raise ValueError('Wait must be between 0.1 and five seconds')
            time.sleep(seconds)
        elif action == 'scroll':
            direction = params.get('direction', 'down')
            if direction not in {'up', 'down', 'left', 'right'}:
                raise ValueError('Invalid scroll direction')
            amount = min(20, max(1, int(params.get('amount', 500)) // 100))
            # The installed PyAutoGUI Windows backend passes raw wheel units,
            # so one wheel notch is WHEEL_DELTA (120), not one raw unit.
            cc._scroll(direction, amount * 120)
        elif action in {'back', 'forward', 'reload', 'close_tab'}:
            if action in {'back', 'forward'}:
                cc._hotkey('alt', 'left' if action == 'back' else 'right')
            elif action == 'reload':
                cc._hotkey('ctrl', 'r')
            else:
                cc._hotkey('ctrl', 'w')
        else:
            return outcome.failed('browser_control', 'Use visible smart_click/smart_type controls or screen_process and computer_control in your personal app; no separate browser was launched')
        return outcome.unverified('browser_control', 'Input delivered to your personal browser. Use screen_process to verify the requested result', browser=selected)
    except InteractionError as exc:
        diagnostics.record(action, exc.code, backend='personal', error_type=type(exc).__name__)
        return outcome.failed('browser_control', str(exc))
    except Exception as exc:
        diagnostics.record(action, 'error', backend='personal', error_type=type(exc).__name__)
        # Avoid exception bodies containing dictated credentials or clipboard data.
        return outcome.failed('browser_control', 'Personal browser operation could not be completed (' + type(exc).__name__ + '). Inspect the current screen; no separate profile was created')
