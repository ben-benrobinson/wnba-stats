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

app.layout = root_layout()
register_callbacks(app)

if __name__ == "__main__":
    app.run(debug=True)
