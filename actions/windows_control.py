"""General observed-control operations for the user's visible Windows apps."""
import json
import os
import platform
import subprocess
from core import accessibility, outcome

SETTINGS = {
    'home': '', 'display': 'display', 'about': 'about', 'sound': 'sound',
    'background': 'personalization-background', 'wallpaper': 'personalization-background',
    'personalization': 'personalization', 'colors': 'colors', 'themes': 'themes',
    'bluetooth': 'bluetooth', 'wifi': 'network-wifi', 'network': 'network-status',
    'storage': 'storagesense', 'power': 'powersleep', 'apps': 'appsfeatures',
    'notifications': 'notifications', 'mouse': 'mousetouchpad', 'keyboard': 'typing',
    'date_time': 'dateandtime', 'windows_update': 'windowsupdate',
    'microphone': 'privacy-microphone', 'camera': 'privacy-webcam',
}

def _windows():
    from pywinauto import Desktop
    return [w for w in Desktop(backend='uia').windows()
            if w.is_visible() and w.window_text() and w.process_id() != os.getpid()]

def _foreground():
    import ctypes
    from ctypes import wintypes
    ctypes.windll.user32.GetForegroundWindow.restype = wintypes.HWND
    return int(ctypes.windll.user32.GetForegroundWindow() or 0)

def _resolve(params, editing=False):
    windows = _windows()
    if editing:
        hwnd = params.get('window_id')
        if not isinstance(hwnd, int) or isinstance(hwnd, bool) or not params.get('snapshot'):
            raise ValueError('Inspect the target app first and use its window_id and snapshot')
        candidates = [w for w in windows if int(w.handle) == hwnd]
    else:
        title = str(params.get('window_title', '')).strip().casefold()
        exact = [w for w in windows if w.window_text().casefold() == title] if title else []
        candidates = exact or ([w for w in windows if title in w.window_text().casefold()] if title else [w for w in windows if int(w.handle) == _foreground()])
    if len(candidates) != 1:
        raise ValueError('Name one visible app window; the target is missing or ambiguous')
    window = candidates[0]
    window.set_focus()
    if _foreground() != int(window.handle):
        raise ValueError('The target window could not be focused; no input was sent')
    return window

def _pc_info():
    # Fixed queries only; never interpolate user input into PowerShell.
    script = """$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new();
$c=Get-CimInstance Win32_ComputerSystem; $o=Get-CimInstance Win32_OperatingSystem;
$p=@(Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors);
$g=@(Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion,CurrentHorizontalResolution,CurrentVerticalResolution);
$d=@(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | Select-Object DeviceID,Size,FreeSpace);
[ordered]@{manufacturer=$c.Manufacturer;model=$c.Model;ram_bytes=$c.TotalPhysicalMemory;windows=$o.Caption;version=$o.Version;build=$o.BuildNumber;architecture=$o.OSArchitecture;processors=$p;graphics=$g;drives=$d} | ConvertTo-Json -Depth 5 -Compress"""
    result = subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],
        capture_output=True,text=True,encoding='utf-8',timeout=25,check=True,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    return json.loads(result.stdout.lstrip('\ufeff'))

def windows_control(parameters=None, response=None, player=None, session_memory=None):
    params = parameters or {}
    if platform.system() != 'Windows':
        return outcome.failed('windows_control','This tool requires Windows')
    action = str(params.get('action','inspect')).strip().lower()
    try:
        if action == 'list_windows':
            rows=[{'window_id':int(w.handle),'title':w.window_text()} for w in _windows()]
            return outcome.untrusted('visible-windows',json.dumps(rows,ensure_ascii=False))
        if action == 'open_settings':
            page=str(params.get('page','home')).strip().lower().replace(' ','_')
            if page not in SETTINGS:
                return outcome.failed('windows_control','Choose an available Settings page: '+', '.join(SETTINGS))
            os.startfile('ms-settings:'+SETTINGS[page])
            return outcome.unverified('windows_control','Requested the Settings page. Inspect its visible controls before claiming it opened.',page=page)
        if action == 'pc_info':
            data=_pc_info()
            if params.get('show_window'):
                os.startfile('ms-settings:about')
            if player and hasattr(player,'show_content'):
                player.show_content('PC DETAILS',json.dumps(data,indent=2,ensure_ascii=False))
            return outcome.done('windows_control',hardware=json.dumps(data,ensure_ascii=False),verified=True)
        if action not in {'inspect','click','type','select_option','set_checked'}:
            return outcome.failed('windows_control','Use inspect, click, type, select_option, set_checked, open_settings or pc_info')
        window=_resolve(params,editing=action!='inspect')
        hwnd=int(window.handle)
        if action=='inspect':
            observed=accessibility.request('inspect',hwnd=hwnd)
            if observed.get('status')!='observed':
                return outcome.failed('windows_control','App controls are unavailable; use screen_process to inspect the visible app')
            observed['window_id']=hwnd
            return outcome.untrusted('windows-app-controls',json.dumps(observed,ensure_ascii=False))
        common=dict(hwnd=hwnd,description=str(params.get('description','')),
                    element_id=str(params.get('element_id','')),snapshot=str(params.get('snapshot','')))
        if not common['description'] and not common['element_id']:
            raise ValueError('Use an observed control name or ID')
        if action=='type':
            if not isinstance(params.get('text'),str):
                raise ValueError('Supply the text to enter')
            focused=accessibility.request('focus',**common)
            if focused.get('status')!='focused' or _foreground()!=hwnd:
                return outcome.failed('windows_control','Field focus was not verified; no text was entered')
            from actions import computer_control as cc
            from core.personal_browser import paste_text
            if params.get('clear_first',True):
                cc._hotkey('ctrl','a')
            paste_text(cc,params['text'])
            return outcome.unverified('windows_control','Text entered into the observed field. Inspect the app to verify; no automatic submission occurred.')
        if action=='select_option':
            if not str(params.get('option','')).strip(): raise ValueError('Name the option')
            common['option']=params['option']
        if action=='set_checked':
            if not isinstance(params.get('checked'),bool): raise ValueError('Specify a true or false checkbox state')
            common['checked']=params['checked']
        result=accessibility.request(action,**common)
        if result.get('status') in {'selected','checked'}:
            return outcome.done('windows_control',control_updated=True,verified=True)
        if not result.get('attempted'):
            return outcome.failed('windows_control','No input sent: '+str(result.get('status'))+'. Inspect the app again.')
        return outcome.unverified('windows_control','Input attempted; inspect the app before claiming the task succeeded. Do not repeat an uncertain operation.')
    except (ValueError,RuntimeError) as exc:
        return outcome.failed('windows_control',str(exc))
    except Exception as exc:
        return outcome.failed('windows_control','The Windows operation could not complete ('+type(exc).__name__+'). No elevation or security bypass was attempted.')

TOOL={
 'name':'windows_control','tier':'core',
 'description': 'Operate visible Windows apps through observed controls. For any everyday OS/app task: open_app if needed, list_windows, inspect the named window, then use its window_id, snapshot and observed control ID for click/type/select_option/set_checked. Inspect again after changes; old snapshots are rejected. Use existing computer_control for scrolling, keys and window movement. Use computer_settings for supported direct system changes and desktop_control for wallpaper. open_settings(page) opens specific Windows settings. pc_info reads actual model, CPU, RAM, Windows, graphics and storage; show_window=true also opens About for the user. Continue until the requested outcome is verified or a concrete blocker requires user input. Never claim universal access, elevate privileges or bypass security prompts. Stop for inaccessible secure dialogs; use the existing confirmation policy for consequential operations. Values typed are not echoed.',
 'brief':'Inspect and operate visible Windows apps, open Settings pages, and read actual PC hardware details.',
 'parameters':{'type':'OBJECT','properties':{
  'action':{'type':'STRING','enum':['list_windows','inspect','click','type','select_option','set_checked','open_settings','pc_info']},
  'window_title':{'type':'STRING','description':'Visible app title for inspect; match one window'},
  'window_id':{'type':'INTEGER','description':'Observed window_id returned by inspect'},
  'snapshot':{'type':'STRING','description':'Fresh snapshot returned by inspect'},
  'description':{'type':'STRING','description':'Observed visible control name'},
  'element_id':{'type':'STRING','description':'Observed control ID'},
  'text':{'type':'STRING','description':'User-supplied text to enter'},
  'option':{'type':'STRING','description':'Exact visible dropdown choice'},
  'checked':{'type':'BOOLEAN'},'clear_first':{'type':'BOOLEAN'},
  'page':{'type':'STRING','enum':list(SETTINGS)},
  'show_window':{'type':'BOOLEAN','description':'For pc_info also open the About page for visual checking'}
 },'required':['action']},'handler':windows_control}
