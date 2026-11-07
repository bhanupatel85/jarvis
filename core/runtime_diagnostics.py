"""Preserve Python callback errors and native crash traces across launch routes."""
import datetime
import faulthandler
from pathlib import Path
import sys
import traceback

_crash_stream = None


def install(log_directory):
    global _crash_stream
    directory = Path(log_directory)
    directory.mkdir(parents=True, exist_ok=True)
    _crash_stream = (directory / 'native-crash.log').open('a', encoding='utf-8')
    faulthandler.enable(file=_crash_stream, all_threads=True)

    def report(kind, value, tb):
        if issubclass(kind, (KeyboardInterrupt, SystemExit)):
            sys.__excepthook__(kind, value, tb)
            return
        # PyQt aborts the process for exceptions escaping a Python callback
        # unless an application exception hook handles them.
        try:
            with (directory / 'callback-errors.log').open('a', encoding='utf-8') as stream:
                stream.write('\n' + datetime.datetime.now(datetime.timezone.utc).isoformat() + '\n')
                traceback.print_exception(kind, value, tb, file=stream)
        except OSError:
            pass
        if sys.stderr is not None:
            traceback.print_exception(kind, value, tb, file=sys.stderr)

    sys.excepthook = report
