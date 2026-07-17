"""Server-emitted Plotly charts for the FastGrants dashboard.

Each helper returns a (Div, Script) pair: an empty target div plus a tiny inline
script that draws the chart with Plotly (loaded from CDN in the layout). No
build step, no client framework.
"""
from __future__ import annotations

import json

from fasthtml.common import Div, Script, NotStr, P

ACCENT = "#1e3a8a"
GOLD = "#c99a06"
OK = "#15803d"
PALETTE = ["#1e3a8a", "#c99a06", "#15803d", "#0e7490", "#7c3aed", "#be123c", "#b45309"]
_BASE_LAYOUT = {
    "margin": {"t": 10, "r": 12, "b": 44, "l": 64},
    "paper_bgcolor": "rgba(0,0,0,0)", "plot_bgcolor": "rgba(0,0,0,0)",
    "font": {"size": 11, "color": "#4a5168"},
    "xaxis": {"automargin": True}, "yaxis": {"automargin": True},
}


def _draw(div_id, traces, layout, height=300):
    lay = {**_BASE_LAYOUT, **layout, "height": height}
    spec = json.dumps({"data": traces, "layout": lay})
    return (Div(id=div_id, cls="plot", style=f"min-height:{height}px;"),
            Script(NotStr(
                f"(function(){{var s={spec};"
                f"Plotly.newPlot('{div_id}',s.data,s.layout,{{displayModeBar:false,responsive:true}});}})();")))


def budget_chart(by_call, div_id="chart-budget", height=320):
    """Grouped bars: budget vs allocated vs disbursed per call."""
    if not by_call:
        return Div(P("No calls yet.", style="color:var(--text-mute);"), cls="plot")
    names = [c["name"].split(" — ")[0][:22] for c in by_call]
    traces = [
        {"type": "bar", "name": "Budget", "x": names, "y": [c["budget_total"] for c in by_call],
         "marker": {"color": "#c7d2ec"}},
        {"type": "bar", "name": "Allocated", "x": names, "y": [c["allocated"] for c in by_call],
         "marker": {"color": ACCENT}},
        {"type": "bar", "name": "Disbursed", "x": names, "y": [c["disbursed"] for c in by_call],
         "marker": {"color": GOLD}},
    ]
    layout = {"barmode": "group", "legend": {"orientation": "h", "y": 1.12, "x": 0},
              "yaxis": {"automargin": True, "tickprefix": "€", "tickformat": ",.0s"}}
    return _draw(div_id, traces, layout, height)


def pipeline_chart(by_status, order, div_id="chart-pipeline", height=320):
    """Horizontal funnel-style bar of applications by workflow stage."""
    xs = [by_status.get(s, 0) for s in order]
    if not any(xs):
        return Div(P("No applications yet.", style="color:var(--text-mute);"), cls="plot")
    colors = {"Draft": "#94a3b8", "Submitted": "#3b82f6", "Under Review": GOLD,
              "Approved": OK, "Rejected": "#be123c"}
    traces = [{"type": "bar", "orientation": "h", "y": order, "x": xs,
               "marker": {"color": [colors.get(s, ACCENT) for s in order]},
               "text": xs, "textposition": "auto"}]
    layout = {"yaxis": {"automargin": True, "autorange": "reversed"},
              "xaxis": {"automargin": True, "dtick": 1}}
    return _draw(div_id, traces, layout, height)


def disbursement_gauge(allocated, disbursed, div_id="chart-gauge", height=260):
    pct = round(100 * disbursed / allocated) if allocated else 0
    traces = [{
        "type": "indicator", "mode": "gauge+number", "value": pct,
        "number": {"suffix": "%", "font": {"size": 30, "color": ACCENT}},
        "gauge": {
            "axis": {"range": [0, 100], "tickcolor": "#94a3b8"},
            "bar": {"color": GOLD},
            "bgcolor": "#eef1f8",
            "steps": [{"range": [0, 100], "color": "#eef1f8"}],
        },
    }]
    return _draw(div_id, traces, {"margin": {"t": 20, "r": 20, "b": 10, "l": 20}}, height)
