"""Single bounded UIA operation against the foreground window; no model calls."""
import contextlib
import hashlib
import json
import re
import sys
import time


def normalize(text):
    return ' '.join(re.sub(r'[^\w\s]', ' ', str(text).casefold()).split())


def choose(records, description, *, editing=False, dialog_only=False, element_id=''):
    """Refuse ambiguous matches and browser-chrome Close buttons for popup requests."""
    target = normalize(description)
    for prefix in ('click on the ', 'click the ', 'the ', 'button ', 'input field '):
        if target.startswith(prefix):
            target = target[len(prefix):]
    target = re.sub(r'\s+(button|link|menu item|input|field|textbox)$', '', target).strip()
    aliases = {target}
    if target.startswith('map zoom '):
        aliases.add(target.removeprefix('map '))
    if 'google maps' in target and 'search' in target and ('input' in target or 'field' in target):
        aliases.add('search google maps')
    if target in {'login', 'log in', 'sign in', 'signin'}:
        aliases |= {'login', 'log in', 'sign in', 'signin'}
    if target in {'close popup', 'close pop up', 'dismiss popup', 'close dialog'}:
        aliases |= {'close', 'dismiss', 'no thanks', 'not now'}
    if editing and target in {'email', 'email address', 'e mail', 'username', 'user name'}:
        aliases |= {'email', 'email address', 'e mail', 'username', 'user name', 'email or phone'}
    if editing and target in {'password', 'your password'}:
        aliases |= {'password', 'your password', 'enter your password'}
    scored = []
    for record in records:
        if not record.get('enabled') or not record.get('visible'):
            continue
        if dialog_only and not record.get('dialog'):
            continue
        if editing and record.get('role') not in {'Edit', 'ComboBox'}:
            continue
        if not editing and record.get('role') not in {'Button', 'Hyperlink', 'MenuItem', 'ListItem', 'TabItem', 'CheckBox', 'RadioButton', 'Edit', 'ComboBox'} and not (target == 'map' and record.get('role') in {'Pane', 'Custom', 'Document', 'Group'}):
            continue
        if element_id:
            if record.get('id') == element_id:
                scored.append((100, record))
            continue
        name = normalize(record.get('name', ''))
        if not name and editing and target in {'password', 'your password'} and record.get('password'):
            name = 'password'
        if not name:
            continue
        if target == 'map' and name.startswith('map use arrow keys to pan the map'):
            score = 100
        elif name in aliases:
            score = 100
        elif any(len(a) >= 4 and re.search(r'\b' + re.escape(a) + r'\b', name) for a in aliases):
            score = 80
        else:
            words = set(target.split()) - {'the', 'a', 'on', 'in', 'field', 'input', 'button', 'link', 'please'}
            matched = words & set(name.split())
            score = 60 if len(words) >= 2 and len(matched) == len(words) else 0
        if score:
            scored.append((score, record))
    if not scored:
        return None, 'not_found'
    best = max(score for score, _ in scored)
    matches = [r for score, r in scored if score == best]
    # A modal control is preferable to the underlying page when labels coincide.
    modal = [r for r in matches if r.get('dialog')]
    if modal:
        matches = modal
    return (matches[0], '') if len(matches) == 1 else (None, 'ambiguous')


def snapshot(window):
    records, wrappers = [], {}
    pending = [(window, False, 0)]
    visited = 0
    while pending and visited < 1200 and len(records) < 180:
        control, in_dialog, depth = pending.pop(0)
        visited += 1
        try:
            info = control.element_info
            visible = bool(control.is_visible())
            if not visible:
                continue
            role = info.control_type
            dialog = in_dialog or (depth > 0 and role == 'Window')
            try:
                dialog = dialog or bool(info.element.CurrentIsDialog)
            except Exception:
                pass
            runtime_id = list(info.runtime_id or [])
            key = hashlib.sha256(json.dumps([runtime_id, info.process_id]).encode()).hexdigest()[:18]
            # Labels and roles only: never read Edit values or password contents.
            record = {'id': key, 'name': str(info.name or '')[:180], 'role': role,
                      'visible': visible, 'enabled': bool(control.is_enabled()), 'dialog': dialog}
            if not record['name'] and role in {'Edit', 'ComboBox'}:
                try:
                    label = info.element.CurrentLabeledBy
                    record['name'] = str(label.CurrentName or '')[:180] if label else ''
                except Exception:
                    pass
            try:
                rect = control.rectangle()
                record['bounds'] = [rect.left, rect.top, rect.right, rect.bottom]
            except Exception:
                pass
            try:
                record['password'] = bool(info.element.CurrentIsPassword)
            except Exception:
                record['password'] = False
            try:
                record['required'] = bool(info.element.CurrentIsRequiredForForm)
            except Exception:
                record['required'] = False
            if role == 'CheckBox':
                try:
                    record['checked'] = control.get_toggle_state() == 1
                except Exception:
                    pass
            if record['name'] or role in {'Edit', 'ComboBox', 'Window'}:
                records.append(record)
                wrappers[key] = control
            if depth < 22:
                pending.extend((child, dialog, depth + 1) for child in control.children())
        except Exception:
            continue
    return records, wrappers


def fingerprint(records):
    return hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()


def execute(params, desktop=None, foreground=None):
    if desktop is None:
        from pywinauto import Desktop
        import ctypes
        from ctypes import wintypes
        desktop = Desktop(backend='uia')
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = wintypes.HWND
        foreground = user32.GetForegroundWindow
    hwnd = int(params.get('hwnd') or foreground())
    if not hwnd or int(foreground()) != hwnd:
        return {'status': 'focus_lost', 'attempted': False, 'reason': 'The target window is not in the foreground.'}
    window = desktop.window(handle=hwnd).wrapper_object()
    before, controls = snapshot(window)
    action = params.get('action', 'inspect')
    if action == 'inspect':
        return {'status': 'observed', 'attempted': False, 'hwnd': hwnd, 'controls': before,
                'snapshot': fingerprint(before)}
    if action == 'focused_field':
        for record in before:
            bounds = record.get('bounds', [])
            inside = len(bounds) == 4 and bounds[0] <= params.get('x', -1) < bounds[2] and bounds[1] <= params.get('y', -1) < bounds[3]
            if inside and record['role'] in {'Edit', 'ComboBox'} and controls[record['id']].has_keyboard_focus():
                return {'status': 'focused', 'attempted': False, 'element_id': record['id'],
                        'password': record.get('password', False)}
        return {'status': 'focus_unverified', 'attempted': False}
    if action not in {'click', 'focus', 'focus_surface', 'fill', 'verify_value', 'select_option', 'set_checked'}:
        return {'status': 'unsupported', 'attempted': False}
    if params.get('snapshot') and params['snapshot'] != fingerprint(before):
        return {'status': 'stale', 'attempted': False, 'reason': 'The window changed. Inspect again before using a control ID.'}
    selected, error = choose(before, params.get('description', ''), editing=action in {'fill', 'focus', 'verify_value'},
                             dialog_only=params.get('dialog_only', False), element_id=params.get('element_id', ''))
    if not selected:
        return {'status': error, 'attempted': False, 'controls': before}
    target = controls[selected['id']]
    if int(foreground()) != hwnd:
        return {'status': 'focus_lost', 'attempted': False}
    if action == 'verify_value':
        if not target.has_keyboard_focus():
            return {'status': 'focus_lost', 'attempted': False}
        if selected.get('password'):
            return {'status': 'private_field', 'attempted': False,
                    'reason': 'Password value is not read back.'}
        try:
            actual = str(target.iface_value.CurrentValue)
            expected = str(params.get('text', ''))
            matches = actual == expected if params.get('clear_first', True) else actual.endswith(expected)
            return {'status': 'value_verified' if matches else 'value_mismatch', 'attempted': False}
        except Exception:
            return {'status': 'value_unavailable', 'attempted': False}
    if action == 'select_option' and selected['role'] != 'ComboBox':
        return {'status': 'unsupported_control', 'attempted': False}
    if action == 'set_checked' and (selected['role'] != 'CheckBox' or not isinstance(params.get('checked'), bool)):
        return {'status': 'unsupported_control', 'attempted': False}
    try:
        if action == 'select_option':
            option = str(params.get('option', ''))
            try:
                if target.selected_text() == option:
                    return {'status': 'selected', 'attempted': False}
            except Exception:
                pass
            # HTML selects in Chromium expose a native popup but do not always
            # implement UIA ExpandCollapse. Observe the popup instead of asking
            # pywinauto to guess a child list that may not exist.
            target.click_input()
            time.sleep(.2)
            options, wrappers = snapshot(window)
            candidates = [item for item in options if item.get('role') in {'ListItem', 'MenuItem'}
                          and item.get('enabled') and normalize(item.get('name', '')) == normalize(option)]
            if len(candidates) != 1:
                return {'status': 'options_observed', 'attempted': True, 'controls': options,
                        'snapshot': fingerprint(options), 'reason': 'Select a unique visible option from the open popup.'}
            if int(foreground()) != hwnd:
                return {'status': 'focus_lost', 'attempted': True}
            wrappers[candidates[0]['id']].click_input()
            deadline = time.monotonic() + 1.5
            actual = None
            while time.monotonic() < deadline:
                try:
                    actual = target.selected_text()
                except Exception:
                    pass
                if actual == option:
                    break
                time.sleep(.1)
            return {'status': 'selected' if actual == option else 'unverified', 'attempted': True}
        elif action == 'set_checked':
            desired = int(params['checked'])
            current = target.get_toggle_state()
            if current != desired:
                target.toggle()
            deadline = time.monotonic() + 1.5
            while target.get_toggle_state() != desired and time.monotonic() < deadline:
                time.sleep(.1)
            return {'status': 'checked' if target.get_toggle_state() == desired else 'unverified', 'attempted': current != desired}
        elif action == 'fill':
            target.set_edit_text(str(params.get('text', '')))
        elif action in {'focus', 'focus_surface'}:
            try:
                target.element_info.element.SetFocus()
            except Exception:
                target.set_focus()
            if not target.has_keyboard_focus():
                # Chromium can acknowledge UIA SetFocus without moving the
                # text caret. Click only the already observed control, then
                # verify actual keyboard focus before any typing is allowed.
                target.click_input()
        else:
            # Invoke the observed accessible control rather than guessing coordinates.
            try:
                invoke = target.iface_invoke
            except Exception:
                invoke = None
            if invoke is not None:
                invoke.Invoke()
            else:
                target.click_input()
    except Exception as exc:
        return {'status': 'unknown', 'attempted': True,
                'reason': 'Control operation raised ' + type(exc).__name__ + '; observe before retrying.'}
    if action in {'focus', 'focus_surface'}:
        return {'status': 'focused' if target.has_keyboard_focus() else 'unverified', 'attempted': True,
                'element_id': selected['id'], 'password': selected.get('password', False)}
    after = before
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        time.sleep(0.15)
        after, _ = snapshot(window)
        if fingerprint(after) != fingerprint(before):
            break
    changed = fingerprint(after) != fingerprint(before)
    dismissed = bool(params.get('dialog_only') and selected.get('dialog') and
                     selected['id'] not in {r['id'] for r in after})
    return {'status': 'dialog_dismissed' if dismissed else 'changed' if changed else 'unchanged',
            'attempted': True, 'controls': after, 'changed': changed,
            'snapshot': fingerprint(after), 'hwnd': hwnd,
            'note': 'A changed screen is evidence of input, not proof of login or task completion.'}


def main():
    try:
        params = json.load(sys.stdin)
        with contextlib.redirect_stdout(sys.stderr):
            result = execute(params)
    except Exception as exc:
        result = {'status': 'unavailable', 'attempted': False,
                  'reason': 'Windows accessibility unavailable: ' + type(exc).__name__}
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    main()
