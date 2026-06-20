import dash
import dash_bootstrap_components as dbc
from dashboard.layout import root_layout
from dashboard.callbacks import register_callbacks

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.DARKLY],
    suppress_callback_exceptions=True,
    title="WNBA Stats",
)
server = app.server  # exposed for gunicorn

# Injected after all other CSS so it wins over Bootstrap DARKLY.
# DARKLY sets body color to a near-white (#dee2e6) which is invisible
# on the dropdown's white background. We force black text here.
app.index_string = """<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
        <style>
            /* Dropdown: black text on white background, always */
            .dash-dropdown .Select-control,
            .dash-dropdown .Select-menu-outer,
            .dash-dropdown .Select-menu,
            .dash-dropdown .Select-option,
            .dash-dropdown .Select-value-label,
            .dash-dropdown .Select-placeholder,
            .dash-dropdown input,
            .VirtualizedSelectOption {
                color: #111111 !important;
                background-color: #ffffff !important;
            }
            .dash-dropdown .Select-option:hover,
            .dash-dropdown .Select-option.is-focused {
                background-color: #dce8f8 !important;
                color: #111111 !important;
            }
            .dash-dropdown .Select-option.is-selected {
                background-color: #4a90d9 !important;
                color: #ffffff !important;
            }
        </style>
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>"""

app.layout = root_layout()
register_callbacks(app)

if __name__ == "__main__":
    app.run(debug=True)
