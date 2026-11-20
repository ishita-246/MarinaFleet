"""
Offline UI preview harness (developer tool, not part of the app).

Why it exists: the real Streamlit package may be unavailable (no network), but the pages in ui/ only talk to a small part
of the Streamlit API. This harness runs the REAL app.py / ui/*.py code against a recording stand-in for `streamlit`, then
writes the captured page as static HTML using the REAL stylesheet (ui/theme.py + ui/styles.css) and the REAL component
markup. Native Streamlit widgets (select boxes, sliders, buttons, tables) are only approximated, so this shows the brand
layer faithfully but is NOT a screenshot of Streamlit itself. Run `streamlit run app.py` for the real thing.

    python tools/preview_harness.py            # writes docs/screenshots/*.png (needs Playwright + Chromium)
"""
from __future__ import annotations

import html
import runpy
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ui import theme as T  # noqa: E402

SHOTS = ROOT / "docs" / "screenshots"


class Node:
    def __init__(self, kind, **attrs):
        self.kind, self.attrs, self.kids = kind, attrs, []

    def add(self, x):
        self.kids.append(x)
        return x


class Ctx:
    """Context manager that makes `node` the current container while inside `with`."""
    def __init__(self, stub, node):
        self.stub, self.node = stub, node

    def __enter__(self):
        self.stub.stack.append(self.node)
        return self

    def __exit__(self, *a):
        self.stub.stack.pop()
        return False

    def __getattr__(self, name):  # column.button(...), slot.markdown(...)
        fn = getattr(self.stub, name)

        def call(*a, **k):
            with self:
                return fn(*a, **k)
        return call


class _RerunException(Exception):
    pass


class RenderStub(types.ModuleType):
    __version__ = "1.99.0"

    def __init__(self, press=(), inputs=None, state=None, active_tab=0):
        super().__init__("streamlit")
        self.PRESS, self.INPUTS, self.active_tab = set(press), dict(inputs or {}), active_tab
        self.session_state = state if state is not None else _State()
        self.root = Node("root")
        self.sidebar_node = Node("sidebar")
        self.stack = [self.root]
        self.sidebar = Ctx(self, self.sidebar_node)
        self.pressed = []

    # --- layout
    def _cur(self):
        return self.stack[-1]

    def columns(self, spec, gap="small", **k):
        n = spec if isinstance(spec, int) else len(spec)
        weights = [1] * n if isinstance(spec, int) else list(spec)
        row = self._cur().add(Node("row", gap=gap))
        return [Ctx(self, row.add(Node("col", w=w))) for w in weights]

    def tabs(self, labels):
        t = self._cur().add(Node("tabs", labels=list(labels)))
        return [Ctx(self, t.add(Node("tab"))) for _ in labels]

    def container(self, border=False, **k):
        return Ctx(self, self._cur().add(Node("bordered" if border else "block")))

    def expander(self, label, **k):
        return Ctx(self, self._cur().add(Node("expander", label=label)))

    def form(self, key, **k):
        return Ctx(self, self._cur().add(Node("form")))

    def empty(self):
        return Ctx(self, Node("slot"))  # throw-away: the loader is not part of the final page

    # --- content
    def markdown(self, body, unsafe_allow_html=False, **k):
        if body.lstrip().startswith("<style>"):
            return
        self._cur().add(Node("html", body=body))

    def caption(self, text, **k):
        self._cur().add(Node("html", body=f'<div data-testid="stCaptionContainer">{html.escape(str(text))}</div>'))

    def divider(self):
        self._cur().add(Node("html", body="<hr>"))

    def code(self, text, language=None, **k):
        self._cur().add(Node("html", body=f'<div data-testid="stCode"><pre>{html.escape(str(text))}</pre></div>'))

    def dataframe(self, df, **k):
        try:
            body = df.head(6).to_html(index=False, border=0, classes="h-df")
        except Exception:
            body = ""
        self._cur().add(Node("html", body=f'<div data-testid="stDataFrame" class="h-approx">{body}</div>'))

    def download_button(self, label, *a, **k):
        self._cur().add(Node("html", body=f'<div class="stDownloadButton"><button><p>{html.escape(label)}</p></button></div>'))
        return False

    # --- widgets
    def button(self, label, key=None, type="secondary", **k):
        hit = any(p in label for p in self.PRESS)
        if hit:
            self.pressed.append(label)
        kind = "primary" if type == "primary" else "secondary"
        self._cur().add(Node("html", body=f'<div class="stButton"><button kind="{kind}" data-testid="stBaseButton-{kind}"><p>{html.escape(label)}</p></button></div>'))
        return hit

    form_submit_button = button

    def _field(self, label, inner):
        self._cur().add(Node("html", body=f'<div class="h-field"><div data-testid="stWidgetLabel"><p>{html.escape(label)}</p></div>{inner}</div>'))

    def selectbox(self, label, options, index=0, key=None, format_func=str, **k):
        opts = list(options)
        val = self.INPUTS.get(key, opts[index])
        self._field(label, f'<div data-baseweb="select"><div>{html.escape(str(format_func(val)))}</div></div>')
        return val

    def text_input(self, label, value="", key=None, type="default", placeholder="", **k):
        shown = "•" * len(value) if type == "password" else (value or placeholder)
        self._field(label, f'<div data-baseweb="input"><div>{html.escape(str(shown))}</div></div>')
        return self.INPUTS.get(key, value)

    def number_input(self, label, min_value=None, max_value=None, value=None, key=None, **k):
        self._field(label, f'<div data-baseweb="input"><div>{value}</div></div>')
        return self.INPUTS.get(key, value)

    def slider(self, label, min_value=None, max_value=None, value=None, key=None, **k):
        self._field(label, f'<div class="h-slider"><span>{value}</span></div>')
        return value

    def toggle(self, label, value=False, **k):
        self._field(label, f'<div class="h-toggle">{"On" if value else "Off"}</div>')
        return value

    checkbox = toggle

    def radio(self, label, options, index=0, **k):
        return list(options)[index]

    # --- misc API used by the app
    def cache_resource(self, *a, **k):
        return a[0] if a and callable(a[0]) else (lambda f: f)

    cache_data = cache_resource

    def set_page_config(self, **k):
        pass

    def rerun(self):
        raise _RerunException()

    def stop(self):
        raise _RerunException()

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *a, **k: None


class _State(dict):
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError as exc:
            raise AttributeError(k) from exc

    def __setattr__(self, k, v):
        self[k] = v


# ----------------------------------------------------------------------------------------------- serialise
def _render(node: Node, stub: RenderStub) -> str:
    k = node.kind
    inner = lambda: "".join(f'<div class="stElementContainer">{_render(c, stub)}</div>' for c in node.kids)  # noqa: E731
    if k == "html":
        return node.attrs["body"]
    if k == "row":
        tot = sum(c.attrs["w"] for c in node.kids)
        return '<div class="h-row" data-testid="stHorizontalBlock">' + "".join(
            f'<div class="h-col" data-testid="stColumn" data-w="{c.attrs["w"] / tot * 100:.2f}">{"".join(_render(x, stub) for x in c.kids)}</div>' for c in node.kids) + "</div>"
    if k == "tabs":
        tabs = "".join(f'<button role="tab" data-baseweb="tab" aria-selected="{str(i == stub.active_tab).lower()}">{html.escape(l)}</button>'
                       for i, l in enumerate(node.attrs["labels"]))
        panel = _render(node.kids[stub.active_tab], stub) if node.kids else ""
        return f'<div class="stTabs"><div data-baseweb="tab-list">{tabs}</div><div data-baseweb="tab-panel">{panel}</div></div>'
    if k in ("tab", "block", "root"):
        return f'<div data-testid="stVerticalBlock">{inner()}</div>'
    if k == "bordered":
        return f'<div data-testid="stVerticalBlockBorderWrapper"><div data-testid="stVerticalBlock">{inner()}</div></div>'
    if k == "form":
        return f'<div data-testid="stForm"><div data-testid="stVerticalBlock">{inner()}</div></div>'
    if k == "expander":
        return f'<div data-testid="stExpander"><details><summary>{html.escape(node.attrs["label"])}</summary></details></div>'
    return ""


HARNESS_CSS = """
/* Approximation of Streamlit's own layout + widget base styles (the real app gets these from Streamlit). */
html,body{margin:0}
.stApp{min-height:100vh;display:flex}
section[data-testid="stSidebar"]{width:336px;flex:none;padding:24px 16px;box-sizing:border-box;position:sticky;top:0;height:100vh;overflow:auto}
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"]{display:flex;flex-direction:column;gap:8px}
.h-main{flex:1;min-width:0}
[data-testid="stVerticalBlock"]{display:flex;flex-direction:column}
.stElementContainer{width:100%}
.h-row{display:flex;gap:24px;width:100%}.h-col{min-width:0}
.h-field{margin-bottom:4px}[data-testid="stWidgetLabel"] p{margin:0 0 4px}
[data-baseweb="select"]>div,[data-baseweb="input"]>div{padding:10px 12px;min-height:22px;box-sizing:content-box;border-radius:8px}
.stButton button,.stDownloadButton button{width:100%;padding:0 16px;cursor:pointer}.stButton button p,.stDownloadButton button p{margin:0}
.stTabs [data-baseweb="tab"]{border:0;background:transparent;cursor:pointer;font-size:14px;display:inline-flex;align-items:center}
[data-baseweb="tab-list"]{display:flex}
[data-testid="stForm"]{box-sizing:border-box}[data-testid="stExpander"] details{padding:12px 16px}
[data-testid="stCaptionContainer"]{margin:4px 0}hr{border:0;border-top:1px solid var(--mf-border);width:100%}
pre{padding:12px;overflow:auto;font-size:13px;color:var(--mf-text);margin:0}
.h-df{border-collapse:collapse;font-size:13px;width:100%}.h-df th,.h-df td{padding:6px 10px;border-bottom:1px solid var(--mf-border);text-align:left}
.h-approx::after{content:"approximation of st.dataframe";display:block;font-size:11px;color:var(--mf-muted);padding:4px 10px}
.h-slider{height:4px;background:var(--mf-border);border-radius:4px;margin:14px 6px 8px;position:relative}.h-slider span{position:absolute;top:-22px;left:0;color:var(--mf-text-2)}
.h-toggle{color:var(--mf-text-2)}
h2{margin:0}
"""


def widths_css() -> str:
    # columns get a proportional flex-basis through data-w (applied with a tiny inline script-free trick: nth rules are generated)
    return ""


def page_html(stub: RenderStub) -> str:
    cols_js = ("<script>document.querySelectorAll('.h-col').forEach(c=>{c.style.flex='0 0 calc('+c.dataset.w+'% - 24px*(1 - '+c.dataset.w+'/100))'})</script>")
    side = f'<section data-testid="stSidebar"><div data-testid="stVerticalBlock">{"".join(f"<div class=stElementContainer>{_render(c, stub)}</div>" for c in stub.sidebar_node.kids)}</div></section>' if stub.sidebar_node.kids else ""
    main = f'<div class="h-main"><div class="block-container">{_render(stub.root, stub)}</div></div>'
    return (f'<!doctype html><html><head><meta charset="utf-8"><title>MarinaFleet preview harness</title><style>{T.stylesheet()}\n{HARNESS_CSS}</style></head>'
            f'<body><div class="stApp" data-testid="stApp">{side}{main}</div>{cols_js}</body></html>')


def run_app(press=(), inputs=None, state=None, active_tab=0) -> RenderStub:
    stub = RenderStub(press, inputs, state, active_tab)
    sys.modules["streamlit"] = stub
    for m in [m for m in sys.modules if m == "ui" or m.startswith("ui.")]:
        del sys.modules[m]  # re-import ui modules against this stub
    try:
        runpy.run_path(str(ROOT / "app.py"), run_name="__main__")
    except _RerunException:
        pass
    return stub


def settle(press=(), inputs=None, state=None, active_tab=0, passes=1) -> RenderStub:
    """Press once, then re-render without pressing (mirrors Streamlit's rerun after a click)."""
    stub = run_app(press, inputs, state, 0)
    st = stub.session_state
    for _ in range(passes):
        stub = run_app((), inputs, st, active_tab)
    return stub
