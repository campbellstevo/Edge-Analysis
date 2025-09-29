from __future__ import annotations 
from pathlib import Path
import base64
import streamlit as st
import altair as alt
import streamlit.components.v1 as components
from PIL import Image

# ───────────────────────── Brand / assets ─────────────────────────
PURPLE_HEX = "#4800ff"
ASSETS_DIR = Path("assets")
RAW_ICON   = ASSETS_DIR / "edge_favicon_mark.png"
FAVI_PNG   = ASSETS_DIR / "edge_favicon_transparent.png"
HEADER_LOGO_LIGHT = ASSETS_DIR / "edge_logo.png"   # light-only
HEADER_LOGO_DARK  = ASSETS_DIR / "edge_logo_dark.png"  # kept for compatibility (not used)


# ───────────────────────── Favicon helpers ─────────────────────────
def _square_canvas(im: Image.Image, size: int = 256) -> Image.Image:
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    im = im.copy()
    im.thumbnail((size-8, size-8), Image.LANCZOS)
    x = (size - im.width)//2
    y = (size - im.height)//2
    canvas.paste(im, (x, y), im)
    return canvas


def setup_favicon():
    try:
        if RAW_ICON.exists():
            im = Image.open(RAW_ICON).convert("RGBA")
            im = _square_canvas(im, 256)
            im.save(FAVI_PNG, optimize=True)
        png = FAVI_PNG if FAVI_PNG.exists() else RAW_ICON
        if not png.exists():
            return
        b64 = base64.b64encode(png.read_bytes()).decode()
        components.html(
            f"""
            <script>
            (function(){{
              const href = "data:image/png;base64,{b64}";
              const rels = ["icon","shortcut icon"];
              rels.forEach(r => {{
                let link = document.querySelector(`link[rel="${{r}}"]`);
                if (!link) {{
                  link = document.createElement('link');
                  link.rel = r;
                  document.head.appendChild(link);
                }}
                link.type = 'image/png';
                link.href = href;
              }});
            }})();
            </script>
            """,
            height=0, width=0
        )
    except Exception:
        pass


# ───────────────────────── Light-only palette ─────────────────────
LIGHT = dict(
    bg="#f6f7fb", card="#ffffff", ink="#0f172a",
    muted="#64748b", grid="#e5e7eb", hover="#f3f4f6",
    chart_bg="#ffffff", accent=PURPLE_HEX, toggle="#000000", border="#d1d5db"
)


# ───────────────────────── Apply theme (LIGHT only) ───────────────
def apply_theme():
    """Lock the UI to LIGHT globally."""
    c = LIGHT
    st.session_state["ui_theme"] = "light"

    # CSS variables
    st.markdown(f"""
    <style>
    :root {{
      --accent:{c['accent']}; --ink:{c['ink']}; --muted:{c['muted']};
      --bg:{c['bg']}; --card:{c['card']}; --grid:{c['grid']}; --hover:{c['hover']};
      --toggle:{c['toggle']}; --border:{c['border']};
    }}
    </style>
    """, unsafe_allow_html=True)

    # Altair defaults (light)
    def _alt():
        return {"config":{
            "background": c["chart_bg"],
            "view": {"stroke": "transparent", "fill": c["chart_bg"]},
            "axis": {"labelColor": c["ink"], "titleColor": c["ink"],
                     "gridColor": c["grid"], "tickColor": c["grid"], "grid": True},
            "legend": {"labelColor": c["ink"], "titleColor": c["ink"]},
        }}
    alt.themes.register("edge_light", _alt)
    alt.themes.enable("edge_light")

    def _styler(chart):
        return chart.configure(background=c["chart_bg"]).configure_view(fill=c["chart_bg"])
    return _styler


# ───────────────────────── Header (light logo) ────────────────────
def _img_tag_from_file(path: Path) -> str:
    try:
        b64 = base64.b64encode(path.read_bytes()).decode()
        return f"<img class='header-logo-img' src='data:image/png;base64,{b64}' alt='Edge Analysis'/>"
    except Exception:
        return ""


def inject_header(_theme_ignored: str = "light"):
    logo_path = HEADER_LOGO_LIGHT if HEADER_LOGO_LIGHT.exists() else HEADER_LOGO_DARK
    if logo_path and logo_path.exists():
        st.markdown(
            f"""
            <div style="display:flex; justify-content:center; margin: 1rem 0;">
                {_img_tag_from_file(logo_path)}
            </div>
            """,
            unsafe_allow_html=True,
        )


# ───────────────────────── Global CSS (light, locked) ────────────
def inject_global_css():
    st.markdown(
        """
        <style>
            /* ── Lock sidebar permanently open & remove toggles ─────────── */
            [data-testid="collapsedControl"],
            [data-testid="stSidebarCollapseButton"],
            [data-testid="stSidebarCollapseControl"],
            button[aria-label="Toggle sidebar"],
            button[title="Collapse sidebar"],
            button[title="Expand sidebar"],
            header [data-testid="baseButton-headerNoPadding"],
            header [data-testid="baseButton-header"],
            [data-testid="stSidebar"] [data-testid="icon-chevron-right"],
            [data-testid="stSidebar"] [data-testid="icon-chevron-left"] {
                display: none !important;
            }

            section[data-testid="stSidebar"] {
                width: 360px !important;
                min-width: 360px !important;
                max-width: 360px !important;
                transform: none !important;
                visibility: visible !important;
                background: var(--card) !important;
                border-right: 1px solid var(--grid) !important;
            }

            /* ── Force all sidebar text/icons black ─────────────────────── */
            section[data-testid="stSidebar"] * { color: var(--ink) !important; }
            section[data-testid="stSidebar"] svg { fill: var(--ink) !important; stroke: var(--ink) !important; }
            section[data-testid="stSidebar"] .block-container { padding-top: 12px; }
            section[data-testid="stSidebar"] label, section[data-testid="stSidebar"] legend {
                color: var(--ink) !important; font-weight: 700;
            }

            /* ── App shell (light) ──────────────────────────────────────── */
            .stApp { background-color: var(--bg); color: var(--ink); }
            .block-container { padding: 18px 26px 52px 26px; max-width: 1400px; }
            header[data-testid="stHeader"] { background: var(--card) !important; border-bottom: 1px solid var(--grid); }
            header[data-testid="stHeader"] * { color: var(--ink) !important; }
            div[data-testid="stToolbar"] { display: none !important; }

            /* ── Controls & menus (stay light on hover/focus) ───────────── */
            [data-baseweb="select"] > div,
            [data-baseweb="input"] > div,
            [data-baseweb="base-input"],
            input, textarea {
                background: var(--card) !important;
                color: var(--ink) !important;
                border: 1px solid var(--border) !important;
                border-radius: 12px !important;
                box-shadow: none !important;
            }
            /* focus/focus-within rings without darkening */
            [data-baseweb="input"]:focus-within > div,
            [data-baseweb="select"]:focus-within > div,
            input:focus, textarea:focus {
                background: var(--card) !important;
                border-color: var(--border) !important;
                outline: none !important;
                box-shadow: 0 0 0 2px rgba(72,0,255,0.10) !important;
            }
            /* buttons */
            .stButton > button {
                background: #ffffff !important;
                color: var(--ink) !important;
                border: 1px solid var(--border) !important;
                border-radius: 12px !important;
                box-shadow: none !important;
                transition: background .12s ease, border-color .12s ease !important;
            }
            .stButton > button:hover,
            .stButton > button:focus { background: #f9fafb !important; border-color: var(--border) !important; }
            .stButton > button:active { background: #f3f4f6 !important; border-color: var(--border) !important; }

            /* ── Menus / popovers ───────────────────────────────────────── */
            [data-baseweb="menu"], [data-baseweb="popover"] [data-baseweb="menu"], ul[role="listbox"] {
              background: var(--card)!important; color: var(--ink)!important; border: 1px solid var(--grid)!important;
              box-shadow: 0 8px 24px rgba(15,23,42,0.12)!important;
            }
            [data-baseweb="menu"] [data-baseweb="menu-item"],
            ul[role="listbox"] [data-baseweb="menu-item"] { background: var(--card)!important; color: var(--ink)!important; }
            [data-baseweb="menu"] [data-baseweb="menu-item"][aria-selected="true"],
            ul[role="listbox"] [data-baseweb="menu-item"][aria-selected="true"],
            [data-baseweb="menu"] [data-baseweb="menu-item"]:hover,
            ul[role="listbox"] [data-baseweb="menu-item"]:hover { background: var(--hover)!important; color: var(--ink)!important; }

            /* ── Expander (header + open content) ───────────────────────── */
            [data-testid="stExpander"] > details {
                background: #ffffff !important;
                border: 1px solid var(--border) !important;
                border-radius: 12px !important;
                overflow: hidden !important;
            }
            [data-testid="stExpander"] summary,
            [data-testid="stExpander"] div[role="button"] {
                background: #f3f4f6 !important;
                color: var(--ink) !important;
                border-bottom: 1px solid var(--border) !important;
                padding: .65rem .9rem !important;
            }
            [data-testid="stExpander"] > details[open] > div {
                background: #ffffff !important;
                padding: .75rem .9rem !important;
            }

            /* ── Alerts (readable text) ─────────────────────────────────── */
            .stAlert {
                background: #ecfdf5 !important;           /* mint */
                border: 1px solid #bbf7d0 !important;
                color: #064e3b !important;                 /* deep green */
                border-radius: 12px !important;
            }
            .stAlert * { color: #064e3b !important; }

            /* ── Tables / tabs / cards ──────────────────────────────────── */
            .header-logo-wrap { display:flex; justify-content:center; align-items:center; margin: 2px 0 8px 0; }
            .header-logo-img  { width: clamp(520px, 40vw, 1100px); height:auto; display:block; }

            .section { background: var(--card); border-radius: 16px; padding: 16px 18px;
                       border: 1px solid rgba(0,0,0,0.06); margin-bottom: 16px;
                       box-shadow: 0 2px 12px rgba(0,0,0,0.06); }
            .kpi-grid { display:grid; grid-template-columns: repeat(6, minmax(0,1fr));
                        gap: 14px; margin: 8px 0 18px 0; }
            .kpi { background: var(--card); border-radius: 16px; padding: 14px 16px;
                   border: 1px solid rgba(0,0,0,0.06); box-shadow: 0 2px 12px rgba(0,0,0,0.06); }
            .kpi .label { font-size: 12px; color: var(--muted); font-weight: 700; text-transform: uppercase; letter-spacing: .04em; }
            .kpi .value { font-size: 28px; font-weight: 900; color: var(--accent); line-height: 1.2; margin-top: 2px; }
            .muted { color: var(--muted); font-size: 13px; }
            .spacer-12 { height: 12px; }
            .stTabs [data-baseweb="tab-list"] { gap:6px; }
            .stTabs [data-baseweb="tab"] { color: var(--muted); background: var(--card);
                                           border-radius: 12px 12px 0 0; padding: 10px 14px; font-weight:700;
                                           border:1px solid var(--grid); border-bottom:none; }
            .stTabs [aria-selected="true"] { color: var(--accent)!important; background: var(--card)!important;
                                             box-shadow: 0 -2px 12px rgba(0,0,0,0.06); }

            /* ── Chat/coach (always light) ──────────────────────────────── */
            .edgecoach { background: #fff !important; color: var(--ink) !important; border: 1px solid var(--grid) !important; border-radius: 12px !important; padding: 12px; }
            .edgecoach .stTextInput input, .edgecoach .stTextArea textarea { background: #fff !important; color: var(--ink) !important; border-color: var(--grid) !important; }
            .edgecoach .msg-user { background: color-mix(in oklab, white, var(--accent) 12%); border: 1px solid color-mix(in oklab, var(--accent), #000 20%); color: var(--ink); border-radius: 10px; padding: 10px 12px; }
            .edgecoach .msg-assistant { background: color-mix(in oklab, white, #000 6%); border: 1px solid var(--grid); color: var(--ink); border-radius: 10px; padding: 10px 12px; }
        </style>
        """,
        unsafe_allow_html=True,
    )
