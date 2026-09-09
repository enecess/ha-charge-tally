"""Externally clocked charging detection with resumable state."""
from datetime import datetime
from decimal import Decimal

from .tariffs import elapsed, utc
from .units import decimal_value


class Detector:
    def __init__(self, start_w: Decimal, end_w: Decimal, start_seconds: float, end_seconds: float):
        self.start_w = decimal_value(start_w, nonnegative=True)
        self.end_w = decimal_value(end_w, nonnegative=True)
        self.start_seconds = decimal_value(start_seconds, nonnegative=True)
        self.end_seconds = decimal_value(end_seconds, nonnegative=True)
        if self.end_w >= self.start_w or not self.start_seconds or not self.end_seconds:
            raise ValueError('Invalid detection thresholds or duration')
        self.state = 'idle'
        self._candidate = None
        self._identity_id = None
        self._last_at = None
        self._blocked = False

    def _interrupt(self):
        if self.state == 'pending_start':
            self.state = 'idle'
            self._identity_id = None
        elif self.state == 'pending_end':
            self.state = 'charging'
        self._candidate = None

    def observe(self, at: datetime, power: Decimal | None, identity_id: str) -> list[dict]:
        at = utc(at)
        if self._last_at is not None and at < self._last_at:
            raise ValueError('Observations must be ordered')
        power = None if power is None else decimal_value(power, nonnegative=True)
        self._last_at = at
        if power is None:
            self._interrupt()
            return []
        if self._blocked:
            if power < self.end_w:
                self._blocked = False
            return []
        if self.state in ('idle', 'pending_start'):
            if power < self.start_w:
                self._interrupt()
                return []
            if self.state == 'idle':
                self.state = 'pending_start'
                self._candidate, self._identity_id = at, identity_id
            if elapsed(self._candidate, at) >= self.start_seconds:
                self.state = 'charging'
                event = {'kind': 'start', 'at': self._candidate.isoformat(), 'identity_id': self._identity_id}
                self._candidate = None
                return [event]
        else:
            if power >= self.end_w:
                self._interrupt()
                return []
            if self.state == 'charging':
                self.state = 'pending_end'
                self._candidate = at
            if elapsed(self._candidate, at) >= self.end_seconds:
                event = {'kind': 'end', 'at': self._candidate.isoformat(), 'identity_id': self._identity_id}
                self.state, self._candidate, self._identity_id = 'idle', None, None
                return [event]
        return []

    def snapshot(self) -> dict:
        return {'state': self.state, 'candidate': self._candidate.isoformat() if self._candidate else None,
                'identity_id': self._identity_id, 'last_at': self._last_at.isoformat() if self._last_at else None,
                'blocked': self._blocked}

    def restore(self, data: dict, interrupted: bool = True):
        state = data['state']
        if state not in ('idle', 'pending_start', 'charging', 'pending_end'):
            raise ValueError('Invalid detector state')
        candidate = utc(datetime.fromisoformat(data['candidate'])) if data.get('candidate') else None
        last = utc(datetime.fromisoformat(data['last_at'])) if data.get('last_at') else None
        if state.startswith('pending') and (candidate is None or last is None or candidate > last):
            raise ValueError('Invalid detector candidate')
        self.state, self._candidate, self._last_at = state, candidate, last
        self._identity_id, self._blocked = data.get('identity_id'), bool(data.get('blocked', False))
        if interrupted:
            self._interrupt()

    def force_stop(self):
        self.state, self._candidate, self._identity_id = 'idle', None, None
        self._blocked = True
