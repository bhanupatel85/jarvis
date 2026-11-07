# Jarvis feature audit

Audit scope: the original source archive `checkpoints/before-jarvis-next-20261020-083923.zip`, the current main application, and the separate Bhanu Jarvis foundation. This is a source-presence audit, not proof that hardware, login or cloud-dependent features work.

The main application remains the integration target. Bhanu Jarvis is a separate small foundation; it has not received all the original features.

| Feature | Main Jarvis implementation | Bhanu Jarvis |
|---|---|---|
| Desktop HUD, avatar, lip sync | main.py, ui.py, core/avatar.py, core/viseme.py | Basic desktop text window |
| Voice conversation, microphones, wake word | main.py, core/stt.py, core/wake_word.py | Optional system speech output |
| Alternate model providers | providers/ | Not implemented |
| Browser and desktop control | actions/browser_control.py, actions/computer_control.py | Open selected websites |
| Project generation and code assistance | actions/dev_agent.py, actions/code_helper.py | Not implemented |
| Memory and settings | memory/ | Local notes |
| Tasks, cancellation and checkpoints | core/tasks.py, core/execution.py | Not implemented |
| Phone dashboard | dashboard/ | Not implemented |
| Weather, news, currency | actions/weather_report.py, actions/web_search.py, actions/currency_convert.py | Not implemented |
| Project knowledge retrieval | core/project_knowledge.py, actions/project_knowledge.py | Not implemented |

Existing development protections include path containment, bounded supervised commands, edit backups, external-change detection, dependency validation and on-screen execution confirmation. New improvements add local project context to planning and an isolated source workspace with syntax checks and diff review. An isolated folder is not an operating-system sandbox; executing generated code still has the current user's privileges.

## Original archive comparison

Original archive contains 21 action modules. Missing action filenames in the current main app: none. This checks module presence, not behavior equivalence.
