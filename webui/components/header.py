"""Header component for the TradingAgents research workspace."""

import dash_bootstrap_components as dbc
from dash import html

from webui.components.api_config_modal import create_config_button


def create_header():
    """Create the compact application header."""
    return html.Header(
        dbc.Row(
            [
                dbc.Col(
                    html.Div(
                        [
                            html.Div(
                                html.I(className="fa-solid fa-chart-line"),
                                className="app-brand-mark",
                                **{"aria-hidden": "true"},
                            ),
                            html.Div(
                                [
                                    html.Div("ALPACA / RESEARCH WORKSPACE", className="app-eyebrow"),
                                    html.H1("Trading desk", className="app-title"),
                                    html.P(
                                        "Multi-agent market research and execution controls",
                                        className="app-subtitle",
                                    ),
                                ],
                                className="app-heading-copy",
                            ),
                        ],
                        className="app-heading-group",
                    ),
                    xs=12,
                    md=True,
                ),
                dbc.Col(
                    create_config_button(),
                    xs=12,
                    md="auto",
                    className="app-header-actions",
                ),
            ],
            className="align-items-center g-3",
        ),
        className="app-header",
    )
