from __future__ import annotations

import streamlit as st


_AIROS_GLOBAL_CSS = r"""
<style>
/* -------------------------------------------------------
   AirOS Review Console — design system (global)
   Flat surfaces, 0.5px borders, semantic color only.
   ------------------------------------------------------- */

:root {
  --font-sans: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
  --font-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;

  --color-background-primary: #ffffff;
  --color-background-secondary: rgba(0,0,0,0.04);
  --color-background-tertiary: rgba(0,0,0,0.02);
  --color-background-info: rgba(0, 116, 217, 0.10);
  --color-background-success: rgba(46, 204, 64, 0.10);
  --color-background-warning: rgba(255, 193, 7, 0.14);
  --color-background-danger: rgba(255, 65, 54, 0.10);

  --color-text-primary: rgba(0,0,0,0.92);
  --color-text-secondary: rgba(0,0,0,0.62);
  --color-text-tertiary: rgba(0,0,0,0.45);
  --color-text-info: #005bbb;
  --color-text-success: #1a7f37;
  --color-text-warning: #8a6d00;
  --color-text-danger: #b42318;

  --color-border-tertiary: rgba(0,0,0,0.15);
  --color-border-secondary: rgba(0,0,0,0.30);
  --color-border-primary: rgba(0,0,0,0.40);
  --color-border-info: rgba(0, 116, 217, 0.35);
  --color-border-success: rgba(46, 204, 64, 0.40);
  --color-border-warning: rgba(255, 193, 7, 0.55);
  --color-border-danger: rgba(255, 65, 54, 0.45);

  --border-radius-md: 8px;
  --border-radius-lg: 12px;

  --accent: #993556; /* AirOS pink */
}

@media (prefers-color-scheme: dark) {
  :root {
    --color-background-primary: rgba(255,255,255,0.04);
    --color-background-secondary: rgba(255,255,255,0.06);
    --color-background-tertiary: rgba(255,255,255,0.03);
    --color-background-info: rgba(0, 116, 217, 0.18);
    --color-background-success: rgba(46, 204, 64, 0.16);
    --color-background-warning: rgba(255, 193, 7, 0.20);
    --color-background-danger: rgba(255, 65, 54, 0.16);

    --color-text-primary: rgba(255,255,255,0.92);
    --color-text-secondary: rgba(255,255,255,0.65);
    --color-text-tertiary: rgba(255,255,255,0.45);

    --color-border-tertiary: rgba(255,255,255,0.14);
    --color-border-secondary: rgba(255,255,255,0.26);
    --color-border-primary: rgba(255,255,255,0.34);
  }
}

html, body, [class*="stApp"] {
  font-family: var(--font-sans);
  color: var(--color-text-primary);
}

/* Titles (sentence case) */
h2 {
  font-size: 20px !important;
  font-weight: 500 !important;
  letter-spacing: 0;
}
h3 {
  font-size: 14px !important;
  font-weight: 500 !important;
}

p, li, label, div {
  font-size: 13px;
  line-height: 1.55;
}

code, pre {
  font-family: var(--font-mono) !important;
  font-size: 12px !important;
}

/* Dividers */
hr {
  border: 0 !important;
  border-top: 0.5px solid var(--color-border-tertiary) !important;
  margin: 20px 0 !important;
}

/* Tabs: flat, border-bottom accent for active */
div[data-baseweb="tab-list"] {
  gap: 2px;
  border-bottom: 0.5px solid var(--color-border-tertiary);
}
button[role="tab"] {
  font-size: 13px !important;
  color: var(--color-text-secondary) !important;
  padding: 5px 10px !important;
  border-radius: var(--border-radius-md) !important;
}
button[role="tab"][aria-selected="true"] {
  color: var(--accent) !important;
  font-weight: 500 !important;
  border-bottom: 2px solid var(--accent) !important;
  border-radius: 0 !important;
}

/* Metrics: make st.metric look like AirOS stat cards */
div[data-testid="stMetric"] {
  background: var(--color-background-secondary);
  border-radius: var(--border-radius-md);
  padding: 14px 16px;
}
div[data-testid="stMetricLabel"] p {
  font-size: 12px !important;
  color: var(--color-text-secondary) !important;
}
div[data-testid="stMetricValue"] {
  font-size: 22px !important;
  font-weight: 500 !important;
  color: var(--color-text-primary) !important;
}

/* Alerts: semantic background + 0.5px border */
div[data-testid="stAlert"] {
  border: 0.5px solid var(--color-border-tertiary) !important;
  border-radius: var(--border-radius-md) !important;
  padding: 10px 14px !important;
}
div[data-testid="stAlert"][kind="info"] {
  background: var(--color-background-info) !important;
  border-color: var(--color-border-info) !important;
  color: var(--color-text-info) !important;
}
div[data-testid="stAlert"][kind="warning"] {
  background: var(--color-background-warning) !important;
  border-color: var(--color-border-warning) !important;
  color: var(--color-text-warning) !important;
}
div[data-testid="stAlert"][kind="error"] {
  background: var(--color-background-danger) !important;
  border-color: var(--color-border-danger) !important;
  color: var(--color-text-danger) !important;
}
div[data-testid="stAlert"][kind="success"] {
  background: var(--color-background-success) !important;
  border-color: var(--color-border-success) !important;
  color: var(--color-text-success) !important;
}

/* Expanders: 0.5px border, flat */
div[data-testid="stExpander"] {
  border: 0.5px solid var(--color-border-tertiary) !important;
  border-radius: var(--border-radius-lg) !important;
}

/* Dataframes: inbox-style — no border radius, hairline dividers */
div[data-testid="stDataFrame"] {
  border: 0.5px solid var(--color-border-tertiary) !important;
  border-radius: 6px !important;
  overflow: hidden;
}

/* Reduce main content top padding */
.main .block-container {
  padding-top: 0.75rem !important;
  padding-bottom: 1rem !important;
}

/* Tighten top-level tab bar padding */
div[data-testid="stTabs"] > div:first-child {
  padding-bottom: 0 !important;
}

/* Remove excess top padding from tab content */
div[data-testid="stTabsContent"] {
  padding-top: 8px !important;
}

/* Compact sidebar */
section[data-testid="stSidebar"] > div {
  padding-top: 16px !important;
}

/* Tighter dividers */
hr {
  margin: 10px 0 !important;
}

/* Tighter captions */
div[data-testid="stCaptionContainer"] p {
  font-size: 12px !important;
  color: var(--color-text-tertiary) !important;
}

/* Compact st.info / st.warning banners */
div[data-testid="stAlert"] {
  padding: 8px 12px !important;
  font-size: 12px !important;
}

/* Chat messages */
div[data-testid="stChatMessage"] {
  padding: 8px 12px !important;
}
</style>
"""


def apply_airos_design_system() -> None:
    """Apply AirOS design-system CSS to the Streamlit app."""
    st.markdown(_AIROS_GLOBAL_CSS, unsafe_allow_html=True)

