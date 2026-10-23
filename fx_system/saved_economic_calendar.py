"""Opt-in read of a private saved envelope, with no fetches or writes."""
import json
import os
import stat
from pathlib import Path
from .financecalendar_adapter import normalize_calendar

CODE_ROOT = Path(__file__).resolve().parents[1]
RELATIVE_PATH = Path('data/economic-calendar/reference.json')
MAX_BYTES = 4 * 1024 * 1024


def _unavailable(reason):
    return {'events': [], 'observed_at_utc': None, 'complete': False,
            'load_status': 'unavailable', 'load_reason': reason}


def load_saved_calendar(root, *, evaluated_at):
    """Read one explicit private input; failures affect calendar context only."""
    try:
        root = Path(root)
        if (not root.is_absolute() or root.is_symlink()
                or root.resolve().is_relative_to(CODE_ROOT) or CODE_ROOT.is_relative_to(root.resolve())):
            return _unavailable('private_location_required')
        root = root.resolve()
        target = root / RELATIVE_PATH
        if any(p.is_symlink() for p in (target, *target.parents) if p.is_relative_to(root)):
            return _unavailable('invalid_private_input')
        if not target.resolve().is_relative_to(root):
            return _unavailable('invalid_private_input')
        descriptor = os.open(target, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        with os.fdopen(descriptor, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                return _unavailable('invalid_private_input')
            content = stream.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            return _unavailable('oversized_private_input')
        value = json.loads(content)
        if not isinstance(value, dict) or value.get('schema') != 'financecalendar_saved_input_v1':
            return _unavailable('invalid_private_input')
        calendar = value.get('calendar')
        if not isinstance(calendar, dict) or type(evaluated_at) is not int:
            return _unavailable('invalid_private_input')
        observed = calendar.get('observed_at_utc')
        if type(observed) is not int or not 0 < observed <= evaluated_at:
            return _unavailable('unusable_acquisition_clock')
        status = value.get('status')
        status = status if isinstance(status, dict) else {}
        result = normalize_calendar(calendar.get('payload'), observed_at_utc=observed,
                                    source_status=status.get('payload'),
                                    status_observed_at_utc=status.get('observed_at_utc'))
        if 'invalid_calendar_page' in result['warnings']:
            return _unavailable('invalid_private_input')
        result['load_status'] = 'saved_reference'
        return result
    except (OSError, ValueError, TypeError, RecursionError):
        return _unavailable('unreadable_private_input')


def configured_calendar(*, evaluated_at):
    """Default is disabled. An explicit private root AND opt-in are required."""
    if os.environ.get('FX_ECONOMIC_CALENDAR_SAVED_ENABLED') != 'true':
        return None
    root = os.environ.get('FX_DATA_ROOT')
    if not root:
        return _unavailable('private_location_required')
    return load_saved_calendar(root, evaluated_at=evaluated_at)


def build_outlook_with_saved_calendar(pairs, quality, *, evaluated_at):
    from .scheduled_outlook import build_scheduled_outlook
    calendar = configured_calendar(evaluated_at=evaluated_at)
    if calendar is None:
        return build_scheduled_outlook(pairs, quality, evaluated_at=evaluated_at)
    return build_scheduled_outlook(pairs, quality, evaluated_at=evaluated_at, economic_calendar=calendar)
