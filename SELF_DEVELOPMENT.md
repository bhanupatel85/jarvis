# Jarvis development workflow

Implemented in this development copy only. Start this copy with Start-Jarvis-Development.cmd; the original app may still be open and must be closed before using another Jarvis instance with microphones.

Ask: "Improve Jarvis: prepare a development workspace, explain the planned change, edit the working copy, and check the relevant tests. Show me the diff before applying."

1. self_development prepare copies supported Python/Markdown source, core/prompt.txt and requirements.txt into development-workspaces/<id>/working and baseline. Credentials, settings JSON, virtual environments and runtime assets are excluded.
2. project_knowledge retrieves source references. code_helper edits the returned working path. The existing code tools and model provider perform planning and edits.
3. self_development check takes workspace_id and test_modules such as ["tests.test_public_data"]. It checks Python syntax and runs unittest under the existing interpreter with a 120-second deadline. A nonzero exit, timeout, cancellation, zero tests, or source modification during tests blocks application. It returns the diff path, output and review_token.
4. Review changes.diff and test evidence. self_development apply takes workspace_id and review_token and requires the existing on-screen human confirmation. It refuses stale working source, altered baselines, or changes to application source since preparation. It supports additions and edits, stores originals, and writes a recovery checkpoint after every file. Multi-file writes are not one atomic transaction; interrupted application can require rollback.
5. Restart Jarvis to load applied updates. self_development rollback requires on-screen confirmation, checks backup integrity and refuses to overwrite later edits. It removes newly added files and restores edited files.

Selected tests establish specific behavior, not full correctness or safety. Source copies are not OS sandboxes: approved tests run with your account privileges. Tests needing assets/settings may require fixtures or additional setup. New packages, binary assets, source deletions and environment upgrades are manual operations. The review token identifies the tested snapshot; on-screen confirmation supplies user authorization. Existing tools retain their existing broad file access, so this is a supervised workflow rather than a tamper-resistant security boundary.

Verification: 52 selected tests passed, including real subprocess tests of apply/rollback, stale edits, failing tests and zero-test detection, plus the existing integration, foundations, public-data and knowledge tests. Live model-driven coding and voice use have not been exercised for this feature.

Audit update: test checks use a fresh bytecode cache; see CODE_AUDIT.md for regression coverage and current limitations.
