from __future__ import annotations
from pathlib import Path
import base64
import streamlit as st
import altair as alt
import streamlit.components.v1 as components
from PIL import Image

PURPLE_HEX = "#4800ff"
ASSETS_DIR = Path("assets")
RAW_ICON   = ASSETS_DIR / "edge_favicon_mark.png"
FAVI_PNG   = ASSETS_DIR / "edge_favicon_transparent.png"
HEADER_LOGO_LIGHT = ASSETS_DIR / "edge_logo.png"
HEADER_LOGO_DARK  = ASSETS_DIR / "edge_logo_dark.png"


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


def _theme_colors(theme: str):
    if theme == "dark":
        return dict(
            bg="#0f1117", card="#0b1220", ink="#e5e7eb",
            muted="#94a3b8", grid="#334155", hover="#1e2633",
            chart_bg="#0b1220", accent=PURPLE_HEX, toggle="#ffffff"
        )
    return dict(
        bg="#f6f7fb", card="#ffffff", ink="#0f172a",
        muted="#64748b", grid="#e5e7eb", hover="#f3f4f6",
        chart_bg="#ffffff", accent=PURPLE_HEX, toggle="#000000"
    )


def apply_theme(theme: str = "light"):
    st.session_state["ui_theme"] = theme
    c = _theme_colors(theme)

    st.markdown(f"""
    <style>
    :root {{
      --accent:{c['accent']}; --ink:{c['ink']}; --muted:{c['muted']};
      --bg:{c['bg']}; --card:{c['card']}; --grid:{c['grid']}; --hover:{c['hover']};
      --toggle:{c['toggle']};
    }}
    </style>
    """, unsafe_allow_html=True)

    def _alt():
        return {"config":{
            "background": c["chart_bg"],
            "view": {"stroke": "transparent", "fill": c["chart_bg"]},
            "axis": {"labelColor": c["ink"], "titleColor": c["ink"], "gridColor": c["grid"], "tickColor": c["grid"], "grid": True},
            "legend": {"labelColor": c["ink"], "titleColor": c["ink"]},
        }}
    key = f"edge_{theme}"
    alt.themes.register(key, _alt)
    alt.themes.enable(key)

    def _styler(chart):
        return chart.configure(background=c["chart_bg"]).configure_view(fill=c["chart_bg"])
    return _styler


def _img_tag_from_file(path: Path) -> str:
    try:
        b64 = base64.b64encode(path.read_bytes()).decode()
        return f"<img class='header-logo-img' src='data:image/png;base64,{b64}' alt='Edge Analysis'/>"
    except Exception:
        return ""


def inject_header(theme: str):
    """Show only the big centered logo (no top notice bar)."""
    logo_path = HEADER_LOGO_DARK if theme == "dark" else HEADER_LOGO_LIGHT
    if logo_path.exists():
        st.markdown(
            f"""
            <div style="display:flex; justify-content:center; margin: 1rem 0;">
                {_img_tag_from_file(logo_path)}
            </div>
            """,
            unsafe_allow_html=True,
        )


def inject_global_css():
    st.markdown(
        """
        <style>
            /* ── Keep sidebar permanently open ───────────────────────────── */
            [data-testid="collapsedControl"] { display: none !important; }
            button[aria-label="Toggle sidebar"] { display: none !important; }
            section[data-testid="stSidebar"] {
                width: 360px !important;
                min-width: 360px !important;
                max-width: 360px !important;
                background: var(--card) !important;
                border-right: 1px solid var(--grid) !important;
            }

            /* Legacy buttons (not used now, but leave styles) */
            .ea-sidebar-btn {
                background: black !important;
                color: white !important;
                border: none !important;
                border-radius: 12px !important;
                padding: 8px 14px !important;
                font-weight: 600 !important;
                cursor: pointer !important;
            }

            /* ── Coach chatbox: force white ──────────────────────────────── */
            .edgecoach { background: white !important; color: #0f172a !important; }
            .edgecoach [data-baseweb="input"] > div { background: white !important; }
            .edgecoach input, .edgecoach textarea { background: white !important; color: #0f172a !important; }
            div[data-testid="stChatInput"] textarea {
                background: white !important;
                color: black !important;
            }
            div[data-testid="stChatMessage"] {
                background: white !important;
                border-radius: 12px !important;
                padding: 0.5rem 0.75rem !important;
                border: 1px solid #e8e8e8 !important;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("""
    <style>
    .stApp { background-color: var(--bg); color: var(--ink); }
    .block-container { padding: 18px 26px 52px 26px; max-width: 1400px; }
    header[data-testid="stHeader"] { background: var(--card) !important; border-bottom: 1px solid var(--grid); }
    header[data-testid="stHeader"] * { color: var(--ink) !important; }
    div[data-testid="stToolbar"] { display:none !important; }
    header [data-testid="baseButton-headerNoPadding"] svg,
    header button[aria-label="Toggle sidebar"] svg,
    button[aria-label="Toggle sidebar"] svg,
    [data-testid="collapsedControl"] svg,
    [data-testid="stSidebar"] [data-testid="icon-chevron-right"] svg,
    [data-testid="stSidebar"] [data-testid="icon-chevron-left"] svg { color: var(--toggle)!important; fill: var(--toggle)!important; stroke: var(--toggle)!important; }
    [data-testid="collapsedControl"] button { background: var(--card)!important; border:1px solid var(--grid)!important; color:var(--toggle)!important; }
    [data-testid="collapsedControl"] button:hover { background: color-mix(in oklab, var(--card), var(--toggle) 8%)!important; }
    section[data-testid="stSidebar"] .block-container { padding-top: 12px; }
    section[data-testid="stSidebar"] label, section[data-testid="stSidebar"] legend { color: var(--ink)!important; font-weight:700; }
    [data-baseweb="select"] > div { background: var(--card)!important; color: var(--ink)!important; border-color: var(--grid)!important; }
    [data-baseweb="select"] svg { color: var(--ink)!important; }
    [data-baseweb="menu"], [data-baseweb="popover"] [data-baseweb="menu"], ul[role="listbox"] {
      background: var(--card)!important; color: var(--ink)!important; border: 1px solid var(--grid)!important;
      box-shadow: 0 8px 24px rgba(15,23,42,0.12)!important;
    }
    [data-baseweb="menu"] [data-baseweb="menu-item"], ul[role="listbox"] [data-baseweb="menu-item"] { background: var(--card)!important; color: var(--ink)!important; }
    [data-baseweb="menu"] [data-baseweb="menu-item"][aria-selected="true"],
    ul[role="listbox"] [data-baseweb="menu-item"][aria-selected="true"],
    [data-baseweb="menu"] [data-baseweb="menu-item"]:hover,
    ul[role="listbox"] [data-baseweb="menu-item"]:hover { background: var(--hover)!important; color: var(--ink)!important; }

    .header-logo-wrap { display:flex; justify-content:center; align-items:center; margin: 2px 0 8px 0; }
    .header-logo-img  { width: clamp(520px, 40vw, 1100px); height:auto; display:block; }

    .section { background: var(--card); border-radius: 16px; padding: 16px 18px; border: 1px solid rgba(0,0,0,0.06); margin-bottom: 16px; box-shadow: 0 2px 12px rgba(0,0,0,0.06); }
    .kpi-grid { display:grid; grid-template-columns: repeat(6, minmax(0,1fr)); gap: 14px; margin: 8px 0 18px 0; }
    .kpi { background: var(--card); border-radius: 16px; padding: 14px 16px; border: 1px solid rgba(0,0,0,0.06); box-shadow: 0 2px 12px rgba(0,0,0,0.06); }
    .kpi .label { font-size: 12px; color: var(--muted); font-weight: 700; text-transform: uppercase; letter-spacing: .04em; }
    .kpi .value { font-size: 28px; font-weight: 900; color: var(--accent); line-height: 1.2; margin-top: 2px; }
    .muted { color: var(--muted); font-size: 13px; }
    .spacer-12 { height: 12px; }
    .stTabs [data-baseweb="tab-list"] { gap:6px; }
    .stTabs [data-baseweb="tab"] { color: var(--muted); background: var(--card); border-radius: 12px 12px 0 0; padding: 10px 14px; font-weight:700; border:1px solid var(--grid); border-bottom:none; }
    .stTabs [aria-selected="true"] { color: var(--accent)!important; background: var(--card)!important; box-shadow: 0 -2px 12px rgba(0,0,0,0.06); }
    .badge { display:inline-flex; align-items:center; gap:8px; background: var(--accent); color: #fff; padding: 4px 12px; border-radius: 999px; font-weight: 800; font-size: 12px; border: 1px solid var(--accent); }
    .table-wrap { overflow-x:auto; background: var(--card); border:1px solid var(--grid); border-radius:12px; box-shadow: 0 2px 12px rgba(0,0,0,0.06); }
    .table-wrap table { width:100%; border-collapse: separate; border-spacing:0; background: var(--card); color: var(--ink); }
    .table-wrap th { position:sticky; top:0; background: var(--card); color: var(--ink); font-weight:700; border-bottom:1px solid var(--grid); }
    .table-wrap td { background: var(--card); color: var(--ink); border-bottom:1px solid var(--grid); }
    .table-wrap tbody tr:nth-child(even) td { background: color-mix(in oklab, var(--card), #000 4%); }
    .table-wrap tbody tr:hover td { background: color-mix(in oklab, var(--card), #000 7%); }
    .table-wrap th, .table-wrap td { padding:10px 12px; }

    /* Coach container: white + message bubbles */
    .edgecoach { background: white !important; color: var(--ink); border: 1px solid var(--grid); border-radius: 12px; padding: 12px; }
    .edgecoach .stTextInput input, .edgecoach .stTextArea textarea { background: white !important; color: var(--ink) !important; border-color: var(--grid) !important; }
    .edgecoach .msg-user { background: color-mix(in oklab, white, var(--accent) 12%); border: 1px solid color-mix(in oklab, var(--accent), #000 20%); color: var(--ink); border-radius: 10px; padding: 10px 12px; }
    .edgecoach .msg-assistant { background: color-mix(in oklab, white, #000 6%); border: 1px solid var(--grid); color: var(--ink); border-radius: 10px; padding: 10px 12px; }
    </style>
    """, unsafe_allow_html=True)
