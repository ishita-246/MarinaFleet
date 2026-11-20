"""
Minimal fake `streamlit` module used ONLY by tests/test_app_smoke.py.

It lets pytest execute app.py top-to-bottom without a browser or the real
Streamlit package, so typos / wrong keys / broken data plumbing in the UI are
caught. It does not test visual layout. Buttons whose label contains one of
the strings in `PRESS` return True, every other widget returns its default.
"""
from __future__ import annotations

import types


class _RerunException(Exception):
    pass


class _StopException(Exception):
    pass


class SessionState(dict):
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError as exc:
            raise AttributeError(k) from exc

    def __setattr__(self, k, v):
        self[k] = v


class _Elem:
    """Generic element: any attribute is a no-op callable returning another element; usable as a context manager."""

    def __init__(self, root):
        self._root = root

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __getattr__(self, name):
        root = self._root
        if hasattr(type(root), name) and not name.startswith("_"):
            return getattr(root, name)
        def fn(*a, **k):
            root.calls.append((name, a, k))
            return _Elem(root)
        return fn


class StreamlitStub(types.ModuleType):
    def __init__(self, press=(), inputs=None):
        super().__init__("streamlit")
        self.PRESS = set(press)
        self.INPUTS = dict(inputs or {})
        self.calls = []
        self.session_state = SessionState()
        self.sidebar = _Elem(self)
        self.pressed = []

    # widgets with return values
    def button(self, label, key=None, **k):
        hit = any(p in label for p in self.PRESS)
        if hit:
            self.pressed.append(label)
        return hit

    def form_submit_button(self, label, **k):
        return self.button(label)

    def cache_resource(self, *a, **k):
        if a and callable(a[0]):
            return a[0]
        return lambda f: f

    cache_data = cache_resource

    def number_input(self, label, min_value=None, max_value=None, value=None, key=None, **k):
        return self.INPUTS.get(key, value)

    def download_button(self, *a, **k):
        return False

    def selectbox(self, label, options, index=0, key=None, **k):
        return self.INPUTS.get(key, list(options)[index])

    def radio(self, label, options, index=0, **k):
        return list(options)[index]

    def slider(self, label, min_value=None, max_value=None, value=None, **k):
        return value

    def text_input(self, label, value="", key=None, **k):
        return self.INPUTS.get(key, value)

    def toggle(self, label, value=False, **k):
        return value

    checkbox = toggle

    def columns(self, spec, **k):
        n = spec if isinstance(spec, int) else len(spec)
        return [_Elem(self) for _ in range(n)]

    def tabs(self, labels):
        return [_Elem(self) for _ in labels]

    def rerun(self):
        raise _RerunException()

    def stop(self):
        raise _StopException()

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        def fn(*a, **k):
            self.calls.append((name, a, k))
            return _Elem(self)
        return fn
