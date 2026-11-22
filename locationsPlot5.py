import os
import glob
import re
import math
import pandas as pd
import folium
from dash import Dash, dcc, html, Input, Output, State, callback_context
import json
import base64
import io

USER_HOME = os.path.expanduser("~")
DATA_ROOT = os.path.join(USER_HOME, "Downloads", "PCC6_DATA")

DATE_KEYS = ["15JUL", "16JUL", "17JUL", "18JUL", "21JUL", "23JUL", "24JUL"]
DATES_CONFIG = {
    date: os.path.join(DATA_ROOT, date) for date in DATE_KEYS
}


def parse_time_to_minutes(time_str):
    if pd.isna(time_str):
        return None
    t_str = str(time_str).strip()
    
    match = re.search(r'(?:T|^)(\d{2}):(\d{2}):\d{2}', t_str)
    if match:
        return int(match.group(1)) * 60 + int(match.group(2))
        
    match_alt = re.search(r'[T_](\d{2})(\d{2})\d{2}', t_str)
    if match_alt:
        return int(match_alt.group(1)) * 60 + int(match_alt.group(2))
        
    return None


def load_clean_file(full_path):
    try:
        df = pd.read_csv(full_path)
        lat_col = "Latitude" if "Latitude" in df.columns else "lat_dd"
        lon_col = "Longitude" if "Longitude" in df.columns else "lon_dd"
        
        if lat_col not in df.columns or lon_col not in df.columns:
            return pd.DataFrame(), None, None, None, None
            
        lob_col = next((c for c in df.columns if "lob" in c.lower() and "deg" in c.lower()), None)
        
        # Detect frequency column (prefer cluster MHz, fall back to raw MHz)
        freq_col = None
        for target in ["freq_cluster_mhz", "freq_raw_mhz"]:
            for c in df.columns:
                if c.lower().strip() == target:
                    freq_col = c
                    break
            if freq_col:
                break
                
        time_col = None
        for target in ["gps_date_time", "sys_date_time", "time"]:
            for col in df.columns:
                if col.lower() == target:
                    time_col = col
                    break
            if time_col:
                break
                
        if not time_col:
            filename = os.path.basename(full_path)
            match_fn = re.search(r'[T_](\d{2})(\d{2})\d{2}', filename)
            if match_fn:
                df['normalized_minutes'] = int(match_fn.group(1)) * 60 + int(match_fn.group(2))
            else:
                return pd.DataFrame(), None, None, None, None
        else:
            df['normalized_minutes'] = df[time_col].apply(parse_time_to_minutes)

        df[lat_col] = pd.to_numeric(df[lat_col], errors="coerce")
        df[lon_col] = pd.to_numeric(df[lon_col], errors="coerce")
        df.dropna(subset=[lat_col, lon_col, 'normalized_minutes'], inplace=True)
        
        if lob_col:
            df[lob_col] = pd.to_numeric(df[lob_col], errors="coerce")
        if freq_col:
            df[freq_col] = pd.to_numeric(df[freq_col], errors="coerce")
            
        return df, lat_col, lon_col, lob_col, freq_col
    except Exception:
        return pd.DataFrame(), None, None, None, None


def discover_tracking_lists(base_dir, keywords, exclude_keywords=None):
    clean_base = base_dir.replace(os.sep, "/")
    search_pattern = f"{clean_base}/**/*.csv"
    
    found_files = glob.glob(search_pattern, recursive=True)
    found_files = sorted(found_files)
    matched_paths = []
    
    for fp in found_files:
        fn_lower = os.path.basename(fp).lower()
        fp_lower = fp.lower()
        matches = (
            any(k.lower() in fn_lower for k in keywords) or 
            any(k.lower() in fp_lower for k in keywords)
        )
        contained_exclusion = False
        if exclude_keywords:
            contained_exclusion = (
                any(e.lower() in fn_lower for e in exclude_keywords) or 
                any(e.lower() in fp_lower for e in exclude_keywords)
            )
        if matches and not contained_exclusion:
            matched_paths.append(fp)
            
    return matched_paths


GLOBAL_DATA_CACHE = {}
print("Parsing tracking files into memory RAM cache...")

for date_key, path_directory in DATES_CONFIG.items():
    print(f"Indexing tracking histories for {date_key}...")
    
    if not os.path.exists(path_directory):
        print(f"WARNING: Target folder path not found: {path_directory}")
        
    use_sensors = date_key in ["18JUL", "21JUL", "23JUL", "24JUL"]
    r1_keys = ["Rabbit_1", "Rabbit1", "Events_List"]
    r2_keys = ["Rabbit_2", "Rabbit2"]
    
    r1_rabbit_paths = discover_tracking_lists(path_directory, r1_keys)
    r2_rabbit_paths = discover_tracking_lists(path_directory, r2_keys)
    
    t1_keys = ["Sensor 10", "Sensor10"] if use_sensors else ["Raven1", "Raven_1"]
    t2_keys = ["Sensor 11", "Sensor11"] if use_sensors else ["Raven2", "Raven_2"]
    t3_keys = ["Sensor 12", "Sensor12"] if use_sensors else ["Raven3", "Raven_3"]
    
    v1_paths = discover_tracking_lists(path_directory, t1_keys, exclude_keywords=["Rabbit"])
    v2_paths = discover_tracking_lists(path_directory, t2_keys, exclude_keywords=["Rabbit"])
    v3_paths = discover_tracking_lists(path_directory, t3_keys, exclude_keywords=["Rabbit"])
    
    r1_parsed = [load_clean_file(p) for p in r1_rabbit_paths]
    r2_parsed = [load_clean_file(p) for p in r2_rabbit_paths]
    v1_parsed = [load_clean_file(p) for p in v1_paths]
    v2_parsed = [load_clean_file(p) for p in v2_paths]
    v3_parsed = [load_clean_file(p) for p in v3_paths]
    
    all_minute_vals = []
    for cached_list in [r1_parsed, r2_parsed, v1_parsed, v2_parsed, v3_parsed]:
        for packed in cached_list:
            df, lat_c, lon_c, lob_c, freq_c = packed
            if not df.empty:
                all_minute_vals.extend(df['normalized_minutes'].tolist())
                
    if all_minute_vals:
        min_minute = int(min(all_minute_vals))
        max_minute = int(max(all_minute_vals))
    else:
        min_minute = 0
        max_minute = 1440
        
    total_found = (
        len(r1_rabbit_paths) + len(r2_rabbit_paths) + 
        len(v1_paths) + len(v2_paths) + len(v3_paths)
    )
    print(f"Successfully cached {total_found} tracking files.")
    
    GLOBAL_DATA_CACHE[date_key] = {
        "r1_rabbit": r1_parsed, "r2_rabbit": r2_parsed,
        "v1_sensor": v1_parsed, "v2_sensor": v2_parsed, "v3_sensor": v3_parsed,
        "min_minute": min_minute, "max_minute": max_minute
    }

print("Cache verification ready. Initializing web layout server....")


def lookup_timeline_scale(selected_date, is_dark=False):
    day_cache = GLOBAL_DATA_CACHE[selected_date]
    m_start = day_cache["min_minute"]
    m_end = day_cache["max_minute"]
    
    total_range = max(1, m_end - m_start)
    text_color = '#f8f9fa' if is_dark else '#212529'
    
    marks = {}
    for step in range(0, total_range + 1, 60):
        total_m = m_start + step
        h = total_m // 60
        m = total_m % 60
        marks[step] = {'label': f"{h:02d}:{m:02d}", 'style': {'color': text_color}}
        
    h_end = m_end // 60
    m_end_inner = m_end % 60
    marks[total_range] = {'label': f"{h_end:02d}:{m_end_inner:02d}", 'style': {'color': text_color}}
    
    return total_range, marks


app = Dash(__name__, suppress_callback_exceptions=True)

app.layout = html.Div([
    html.Div(
        style={'display': 'none'},
        children=html.Iframe(
            srcDoc="""
            <style>
                html, body {
                    margin: 0 !important;
                    padding: 0 !important;
                    overflow: hidden !important;
                    width: 50% !important;
                    height: 50% !important;
                }
                ::-webkit-scrollbar {
                    display: none !important;
                    width: 0 !important;
                    height: 0 !important;
                }
            </style>
            """
        )
    ),
    
    dcc.Store(id='chat-history-store', data=[]),
    dcc.Store(id='bot-features-store', data={}),
    dcc.Store(id='active-handle-store', data={'handle': 0, 'prev_val': None}),
    dcc.Store(id='live-map-payload', data={}),
    html.Div(id='postmessage-bridge', style={'display': 'none'}),
    html.Button(id='handle-0-focus-btn', n_clicks=0, style={'display': 'none'}),
    html.Button(id='handle-1-focus-btn', n_clicks=0, style={'display': 'none'}),
    html.Iframe(
        style={'display': 'none'},
        srcDoc="""
        <script>
            setInterval(function() {
                var doc = window.parent.document;
                var handles = doc.querySelectorAll('#slider-wrapper-container .rc-slider-handle');
                if (handles.length >= 2) {
                    if (!handles[0].dataset.hooked) {
                        handles[0].dataset.hooked = '1';
                        handles[0].addEventListener('pointerdown', function() {
                            var b0 = doc.getElementById('handle-0-focus-btn');
                            if (b0) b0.click();
                        });
                    }
                    if (!handles[1].dataset.hooked) {
                        handles[1].dataset.hooked = '1';
                        handles[1].addEventListener('pointerdown', function() {
                            var b1 = doc.getElementById('handle-1-focus-btn');
                            if (b1) b1.click();
                        });
                    }
                }
            }, 300);
        </script>
        """
    ),
    
    html.Div([
        html.H1(
            "Sensor Tracking Dashboard", 
            id="dashboard-title",
            style={'textAlign': 'center', 'fontFamily': 'sans-serif', 'margin': '0', 'flex': '1'}
        ),
        html.Button(
            "🌙 Dark Mode", id="dark-mode-btn", n_clicks=0,
            style={
                'padding': '6px 12px', 'fontFamily': 'sans-serif', 'fontWeight': 'bold',
                'cursor': 'pointer', 'borderRadius': '4px', 'border': '1px solid #ccc',
                'backgroundColor': '#212529', 'color': 'white', 'marginRight': '15px'
            }
        )
    ], id="header-bar", style={
        'display': 'flex', 'alignItems': 'center', 'justifyContent': 'space-between',
        'padding': '10px 0'
    }),
    dcc.Tabs(
        id="date-tabs", value="15JUL", 
        children=[dcc.Tab(label=date, value=date) for date in DATES_CONFIG.keys()],
        style={'fontFamily': 'sans-serif'}
    ),
    
        html.Div([
            html.Button(
                "▶ Play", id="play-button", n_clicks=0,
                style={
                    'marginRight': '15px', 'fontWeight': 'bold', 
                    'padding': '5px 15px', 'fontFamily': 'sans-serif',
                    'cursor': 'pointer', 'borderRadius': '4px',
                    'border': '1px solid #ccc', 'backgroundColor': '#f8f9fa'
                }
            ),
            html.Div([
                html.Label("Slider Mode:", id="slider-mode-label", style={'fontWeight': 'bold', 'fontFamily': 'sans-serif', 'marginRight': '6px'}),
                dcc.RadioItems(
                    id='slider-mode-toggle',
                    options=[
                        {'label': 'Range Window', 'value': 'RANGE'},
                        {'label': 'Single Marker', 'value': 'SINGLE'}
                    ],
                    value='RANGE',
                    inline=True,
                    labelStyle={'marginRight': '6px', 'display': 'inline-flex', 'alignItems': 'center', 'cursor': 'pointer'},
                    inputStyle={'marginRight': '3px'},
                    style={'fontFamily': 'sans-serif', 'display': 'inline-flex', 'alignItems': 'center', 'marginRight': '15px'}
                )
            ], style={'display': 'flex', 'alignItems': 'center'}),

            dcc.RadioItems(
                id='active-handle-selector',
                options=[
                    {'label': 'Start Marker', 'value': 0},
                    {'label': 'End Marker', 'value': 1}
                ],
                value=0,
                inline=False,
                labelStyle={'display': 'flex', 'alignItems': 'center', 'marginBottom': '2px', 'cursor': 'pointer'},
                inputStyle={'marginRight': '4px'},
                style={
                    'fontFamily': 'sans-serif', 'fontSize': '12px', 
                    'display': 'flex', 'flexDirection': 'column', 
                    'justifyContent': 'center', 'marginRight': '15px'
                }
            ),
            
            html.Div(
                id='slider-wrapper-container', 
                children=[
                    dcc.RangeSlider(id='time-slider', min=0, max=100, step=1, value=[0, 100])
                ],
                style={'flex': '1'}
            ),
            
            dcc.Interval(
                id="play-interval", interval=300, n_intervals=0, disabled=True
            ),
        ], id="controls-container", style={
            'width': '96%', 'margin': 'auto', 'padding': '15px 0 10px 0',
            'display': 'flex', 'alignItems': 'center', 'boxSizing': 'border-box'
        }),
    
    html.Div([
        html.Div([
            html.Iframe(
                id='folium-map', width='90%', height='100%', style={'border': 'none'}
            )
        ], style={'width': '75%', 'height': '95%', 'position': 'relative', 'overflow': 'hidden'}),
        
        html.Div([
            html.Div([
                html.Div(
                    "AI Tracking Assistant", 
                    style={'fontWeight': 'bold', 'color': 'white'}
                ),
                html.Button(
                    "🗑️ Reset Chat", id='chat-reset-btn', n_clicks=0,
                    style={
                        'backgroundColor': '#dc3545', 'color': 'white', 
                        'border': 'none', 'borderRadius': '4px', 'padding': '4px 8px', 
                        'fontSize': '11px', 'cursor': 'pointer', 'fontWeight': 'bold'
                    }
                )
            ], style={
                'display': 'flex', 'justifyContent': 'space-between', 'alignItems': 'center',
                'padding': '10px', 'backgroundColor': '#007bff', 'borderRadius': '4px 4px 0 0',
                'boxSizing': 'border-box'
            }),
            
            html.Div(
                id='chat-conversation-area', 
                style={
                    'flex': '1', 'overflowY': 'auto', 'padding': '10px', 
                    'backgroundColor': '#f1f3f5', 'fontSize': '13px'
                }
            ),
            
            html.Div([
                dcc.Upload(
                    id='chat-file-upload',
                    children=html.Button(
                        "📎",
                        title="Upload .csv or .txt file with coordinates/sensors",
                        style={
                            'padding': '6px 10px', 'marginRight': '5px',
                            'backgroundColor': '#6c757d', 'color': 'white',
                            'border': 'none', 'borderRadius': '4px', 'cursor': 'pointer'
                        }
                    ),
                    accept='.csv,.txt',
                    multiple=False
                ),
                dcc.Input(
                    id='chat-user-input', type='text', 
                    placeholder='e.g. 35.21, -116.64 name="Sensor X" time=14:30 lob=145',
                    style={'flex': '1', 'padding': '6px', 'border': '1px solid #ccc', 'borderRadius': '4px'},
                    n_submit=0
                ),
                html.Button(
                    "Send", id='chat-send-btn', n_clicks=0,
                    style={'padding': '8px 12px', 'marginLeft': '5px', 'backgroundColor': '#28a745', 'color': 'white', 'border': 'none', 'borderRadius': '4px', 'cursor': 'pointer'}
                )
            ], id="chat-input-bar", style={'display': 'flex', 'alignItems': 'center', 'padding': '10px', 'backgroundColor': '#fff', 'borderTop': '1px solid #ddd'}),
            
            html.Iframe(
                srcDoc="""
                <script>
                    window.parent.document.addEventListener("DOMContentLoaded", function() {
                        var checkExist = setInterval(function() {
                            var target = window.parent.document.getElementById('chat-conversation-area');
                            if (target) {
                                clearInterval(checkExist);
                                var observer = new MutationObserver(function() {
                                    setTimeout(function() {
                                        target.scrollTop = target.scrollHeight;
                                    }, 20);
                                });
                                observer.observe(target, { childList: true, subtree: true });
                            }
                        }, 100);
                    });
                </script>
                """,
                style={'display': 'none'}
            )
            
        ], style={
            'width': '27.5%', 'height': '95%', 'display': 'flex', 'flexDirection': 'column', 
            'borderLeft': '0px solid #ddd', 'boxSizing': 'border-box', 'fontFamily': 'sans-serif',
            'overflow': 'hidden', 'marginLeft': '-142px'
        })
    ], style={
        'flex': '1', 'width': '100vw', 'display': 'flex', 'flexDirection': 'row', 'overflow': 'hidden', 'boxSizing': 'border-box'
    })
], id="main-layout", style={
    'display': 'flex', 'flexDirection': 'column', 'height': '98vh', 'width': '99vw', 
    'margin': '0', 'padding': '0', 'overflow': 'hidden', 'boxSizing': 'border-box'
})

@app.callback(
    [Output('dark-mode-btn', 'children'),           # 1
     Output('dark-mode-btn', 'style'),              # 2
     Output('main-layout', 'style'),                # 3
     Output('dashboard-title', 'style'),            # 4
     Output('controls-container', 'style'),         # 5
     Output('play-button', 'style'),                # 6
     Output('slider-mode-label', 'style'),          # 7
     Output('slider-mode-toggle', 'labelStyle'),    # 8
     Output('active-handle-selector', 'labelStyle'),# 9
     Output('chat-conversation-area', 'style'),     # 10
     Output('chat-input-bar', 'style'),             # 11
     Output('chat-user-input', 'style'),            # 12
     Output('date-tabs', 'colors'),                 # 13
     Output('date-tabs', 'children')],              # 14 <-- ADD THIS OUTPUT
    [Input('dark-mode-btn', 'n_clicks')]
)
def toggle_dark_mode(n_clicks):
    is_dark = (n_clicks or 0) % 2 == 1

    if is_dark:
        btn_label = "☀️ Light Mode"
        btn_style = {
            'padding': '6px 12px', 'fontFamily': 'sans-serif', 'fontWeight': 'bold',
            'cursor': 'pointer', 'borderRadius': '4px', 'border': '1px solid #555',
            'backgroundColor': '#f8f9fa', 'color': '#212529', 'marginRight': '15px'
        }
        main_style = {
            'display': 'flex',
            'flexDirection': 'column',
            'position': 'fixed',
            'top': '0',
            'left': '0',
            'right': '0',
            'bottom': '0',
            'margin': '0',
            'padding': '0',
            'overflow': 'hidden',
            'boxSizing': 'border-box',
            'backgroundColor': '#121212'
        }
        title_style = {
            'textAlign': 'center', 'fontFamily': 'sans-serif', 'margin': '0',
            'flex': '1', 'color': '#f8f9fa'
        }
        controls_style = {
            'width': '96%', 'margin': 'auto', 'padding': '15px 0 10px 0',
            'display': 'flex', 'alignItems': 'center', 'boxSizing': 'border-box'
        }
        play_style = {
            'marginRight': '15px', 'fontWeight': 'bold', 'padding': '5px 15px',
            'fontFamily': 'sans-serif', 'cursor': 'pointer', 'borderRadius': '4px',
            'border': '1px solid #555', 'backgroundColor': '#2b3035', 'color': '#f8f9fa'
        }
        slider_label_style = {
            'fontWeight': 'bold', 'fontFamily': 'sans-serif',
            'marginRight': '6px', 'color': '#f8f9fa'
        }
        mode_label_style = {
            'marginRight': '6px', 'display': 'inline-flex', 'alignItems': 'center',
            'cursor': 'pointer', 'color': '#f8f9fa'
        }
        handle_label_style = {
            'display': 'flex', 'alignItems': 'center', 'marginBottom': '2px',
            'cursor': 'pointer', 'color': '#f8f9fa'
        }
        chat_area_style = {
            'flex': '1', 'overflowY': 'auto', 'padding': '10px',
            'backgroundColor': '#1e1e1e', 'color': '#e9ecef', 'fontSize': '13px'
        }
        chat_bar_style = {
            'display': 'flex', 'padding': '10px',
            'backgroundColor': '#252526', 'borderTop': '1px solid #3c3c3c'
        }
        input_style = {
            'flex': '1', 'padding': '6px', 'border': '1px solid #555', 'borderRadius': '4px',
            'backgroundColor': '#333333', 'color': '#ffffff'
        }
        tab_colors = {'border': '#3c3c3c', 'primary': '#0d6efd', 'background': '#1e1e1e'}
        tab_style = {
            'backgroundColor': '#1e1e1e', 'color': '#ced4da',
            'borderColor': '#3c3c3c', 'padding': '10px'
        }
        tab_selected_style = {
            'backgroundColor': '#2b3035', 'color': '#ffffff',
            'borderColor': '#3c3c3c', 'borderTop': '2px solid #0d6efd',
            'fontWeight': 'bold', 'padding': '10px'
        }
    else:
        btn_label = "🌙 Dark Mode"
        btn_style = {
            'padding': '6px 12px', 'fontFamily': 'sans-serif', 'fontWeight': 'bold',
            'cursor': 'pointer', 'borderRadius': '4px', 'border': '1px solid #ccc',
            'backgroundColor': '#212529', 'color': 'white', 'marginRight': '15px'
        }
        main_style = {
            'display': 'flex', 'flexDirection': 'column', 'height': '98vh', 'width': '99vw',
            'margin': '0', 'padding': '0', 'overflow': 'hidden', 'boxSizing': 'border-box',
            'backgroundColor': '#ffffff'
        }
        title_style = {
            'textAlign': 'center', 'fontFamily': 'sans-serif', 'margin': '0',
            'flex': '1', 'color': '#212529'
        }
        controls_style = {
            'width': '96%', 'margin': 'auto', 'padding': '15px 0 10px 0',
            'display': 'flex', 'alignItems': 'center', 'boxSizing': 'border-box'
        }
        play_style = {
            'marginRight': '15px', 'fontWeight': 'bold', 'padding': '5px 15px',
            'fontFamily': 'sans-serif', 'cursor': 'pointer', 'borderRadius': '4px',
            'border': '1px solid #ccc', 'backgroundColor': '#f8f9fa', 'color': '#212529'
        }
        slider_label_style = {
            'fontWeight': 'bold', 'fontFamily': 'sans-serif',
            'marginRight': '6px', 'color': '#212529'
        }
        mode_label_style = {
            'marginRight': '6px', 'display': 'inline-flex', 'alignItems': 'center',
            'cursor': 'pointer', 'color': '#212529'
        }
        handle_label_style = {
            'display': 'flex', 'alignItems': 'center', 'marginBottom': '2px',
            'cursor': 'pointer', 'color': '#212529'
        }
        chat_area_style = {
            'flex': '1', 'overflowY': 'auto', 'padding': '10px',
            'backgroundColor': '#f1f3f5', 'color': '#212529', 'fontSize': '13px'
        }
        chat_bar_style = {
            'display': 'flex', 'padding': '10px',
            'backgroundColor': '#fff', 'borderTop': '1px solid #ddd'
        }
        input_style = {
            'flex': '1', 'padding': '6px', 'border': '1px solid #ccc', 'borderRadius': '4px',
            'backgroundColor': '#ffffff', 'color': '#212529'
        }
        tab_colors = {'border': '#d6d6d6', 'primary': '#1975FA', 'background': '#f9f9f9'}
        tab_style = {
            'backgroundColor': '#f9f9f9', 'color': '#212529',
            'borderColor': '#d6d6d6', 'padding': '10px'
        }
        tab_selected_style = {
            'backgroundColor': '#ffffff', 'color': '#212529',
            'borderColor': '#d6d6d6', 'borderTop': '2px solid #1975FA',
            'fontWeight': 'bold', 'padding': '10px'
        }

    tab_children = [
        dcc.Tab(
            label=date,
            value=date,
            style=tab_style,
            selected_style=tab_selected_style
        )
        for date in DATES_CONFIG.keys()
    ]

    return (
        btn_label,          # 1
        btn_style,          # 2
        main_style,         # 3
        title_style,        # 4
        controls_style,     # 5
        play_style,         # 6
        slider_label_style, # 7
        mode_label_style,   # 8
        handle_label_style, # 9
        chat_area_style,    # 10
        chat_bar_style,     # 11
        input_style,        # 12
        tab_colors,         # 13
        tab_children        # 14
    )

@app.callback(
    [Output('active-handle-store', 'data'),
     Output('active-handle-selector', 'value')],
    [Input('active-handle-selector', 'value'),
     Input('time-slider', 'value'),
     Input('date-tabs', 'value')],
    [State('active-handle-store', 'data'),
     State('play-interval', 'disabled'),
     State('slider-mode-toggle', 'value')]
)
def track_highlighted_handle(selected_handle, current_val, selected_date, store_data, is_disabled, mode):
    ctx = callback_context
    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0] if ctx.triggered else None
    store_data = store_data or {'handle': 0, 'prev_val': None}

    if trigger_id == 'date-tabs' or mode == 'SINGLE':
        return {'handle': 0, 'prev_val': current_val}, 0

    if trigger_id == 'active-handle-selector':
        return {'handle': selected_handle, 'prev_val': current_val}, selected_handle

    active_handle = store_data.get('handle', 0)
    prev_val = store_data.get('prev_val')

    if is_disabled and isinstance(current_val, list) and len(current_val) == 2 and isinstance(prev_val, list) and len(prev_val) == 2:
        if current_val[0] != prev_val[0] and current_val[1] == prev_val[1]:
            active_handle = 0
        elif current_val[1] != prev_val[1] and current_val[0] == prev_val[0]:
            active_handle = 1

    return {'handle': active_handle, 'prev_val': current_val}, active_handle

@app.callback(
    Output('slider-wrapper-container', 'children'),
    [Input('slider-mode-toggle', 'value'),
     Input('date-tabs', 'value'),
     Input('dark-mode-btn', 'n_clicks')]
)
def render_dynamic_slider_component(mode, selected_date, dark_clicks):
    is_dark = (dark_clicks or 0) % 2 == 1
    total_range, marks = lookup_timeline_scale(selected_date, is_dark=is_dark)
    if mode == 'SINGLE':
        return dcc.Slider(
            id='time-slider', min=0, max=total_range, step=1, value=0,
            marks=marks, updatemode='mouseup'
        )
    else:
        return dcc.RangeSlider(
            id='time-slider', min=0, max=total_range, step=1, value=[0, total_range],
            marks=marks, updatemode='mouseup'
        )

@app.callback(
    [Output('play-button', 'children'),
     Output('play-interval', 'disabled')],
    [Input('play-button', 'n_clicks'),
     Input('time-slider', 'value')],
    [State('time-slider', 'max'),
     State('play-interval', 'disabled'),
     State('active-handle-store', 'data')]
)
def toggle_playback(n_clicks, current_slider_val, max_val, is_disabled, store_data):
    ctx = callback_context
    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0] if ctx.triggered else None

    if not trigger_id or current_slider_val is None:
        return "▶ Play", True

    active_handle = (store_data or {}).get('handle', 0)
    at_end = False

    if isinstance(current_slider_val, list) and len(current_slider_val) >= 2:
        if active_handle == 0 and current_slider_val[0] >= current_slider_val[1]:
            at_end = True
        elif active_handle == 1 and max_val is not None and current_slider_val[1] >= max_val:
            at_end = True
    else:
        if max_val is not None and current_slider_val >= max_val:
            at_end = True

    if trigger_id == 'time-slider':
        if at_end:
            return "▶ Play", True
        return ("▶ Play", True) if is_disabled else ("⏸ Pause", False)

    if trigger_id == 'play-button':
        if is_disabled:
            if at_end:
                return "▶ Play", True
            return "⏸ Pause", False
        return "▶ Play", True

    return "▶ Play", True

@app.callback(
    [Output('chat-history-store', 'data'),
     Output('bot-features-store', 'data'),
     Output('chat-user-input', 'value'),
     Output('chat-file-upload', 'contents')],
    [Input('chat-send-btn', 'n_clicks'),
     Input('chat-user-input', 'n_submit'),
     Input('chat-reset-btn', 'n_clicks'),
     Input('chat-file-upload', 'contents')],
    [State('chat-file-upload', 'filename'),
     State('chat-user-input', 'value'),
     State('chat-history-store', 'data'),
     State('bot-features-store', 'data'),
     State('date-tabs', 'value')]
)
def process_chatbot_intelligence(clicks, sub, reset_clicks, upload_contents, upload_filename, text, history, features, current_date):
    ctx = callback_context
    if not ctx.triggered:
        return history, features, text, None

    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0] if ctx.triggered else None

    if trigger_id == 'chat-reset-btn':
        return [], features, "", None

    history = history or []
    features = features or {}
    if current_date not in features:
        features[current_date] = {}

    day_cache = GLOBAL_DATA_CACHE[current_date]
    day_min, day_max = day_cache["min_minute"], day_cache["max_minute"]
    valid_folium_colors = [
        'red', 'blue', 'green', 'purple', 'orange', 'darkred', 'lightred', 'beige',
        'darkblue', 'darkgreen', 'cadetblue', 'pink', 'lightblue', 'lightgreen',
        'gray', 'black', 'lightgray'
    ]

    # ─── CASE A: FILE UPLOADED (.CSV OR .TXT) ───────────────────────────────
    if trigger_id == 'chat-file-upload' and upload_contents:
        history.append({"speaker": "user", "text": f"📎 Uploaded file: **{upload_filename}**"})
        try:
            _, content_string = upload_contents.split(',', 1)
            decoded_text = base64.b64decode(content_string).decode('utf-8', errors='replace')

            added_count = 0
            skipped_count = 0
            updated_tracks = set()

            if upload_filename and upload_filename.lower().endswith('.csv'):
                df = pd.read_csv(io.StringIO(decoded_text))
                cols_lower = {c.lower().strip(): c for c in df.columns}

                lat_col = next((cols_lower[k] for k in ['lat', 'latitude', 'lat_dd'] if k in cols_lower), None)
                lon_col = next((cols_lower[k] for k in ['lon', 'lng', 'longitude', 'lon_dd'] if k in cols_lower), None)
                time_col = next((cols_lower[k] for k in ['time', 'timestamp', 'gps_date_time', 'sys_date_time'] if k in cols_lower), None)
                name_col = next((cols_lower[k] for k in ['name', 'sensor', 'label', 'id'] if k in cols_lower), None)
                color_col = next((cols_lower[k] for k in ['color', 'colour'] if k in cols_lower), None)
                lob_col = next(
                    (orig for low, orig in cols_lower.items() if "lob" in low and "deg" in low),
                    next((orig for low, orig in cols_lower.items() if "lob" in low or "bearing" in low), None)
                )

                if not lat_col or not lon_col or not time_col:
                    bot_response = "❌ **CSV Format Error:** File must include `lat` (or `Latitude`), `lon` (or `Longitude`), and `time` (`HH:MM`) columns."
                    history.append({"speaker": "assistant", "text": bot_response})
                    return history, features, "", None

                base_filename = os.path.splitext(upload_filename)[0].strip()

                # ─── 1. DETECT RABBIT VS SENSOR BEFORE ROW LOOP ─────────────
                fn_lower = upload_filename.lower()
                is_rabbit_file = (
                    any(k in fn_lower for k in ["rabbit", "events_list", "eventslist"])
                    or lob_col is None
                )
                # ───────────────────────────────────────────────────────────

                for idx, row in df.iterrows():
                    try:
                        lat = float(row[lat_col])
                        lon = float(row[lon_col])
                        t_raw = str(row[time_col]).strip()
                        t_match = re.search(r'(\d{1,2})[:_](\d{2})', t_raw)
                        if not t_match:
                            skipped_count += 1
                            continue

                        calc_min = int(t_match.group(1)) * 60 + int(t_match.group(2))
                        if calc_min < day_min or calc_min > day_max:
                            skipped_count += 1
                            continue

                        time_str = f"{int(t_match.group(1)):02d}:{int(t_match.group(2)):02d}"

                        if name_col and pd.notna(row[name_col]) and str(row[name_col]).strip():
                            label = str(row[name_col]).strip()
                        else:
                            label = base_filename

                        raw_color = str(row[color_col]).strip().lower() if (color_col and pd.notna(row[color_col])) else "darkgreen"
                        chosen_color = raw_color if raw_color in valid_folium_colors else "darkgreen"

                        raw_lob = pd.to_numeric(row[lob_col], errors='coerce') if lob_col else None
                        lob_val = float(raw_lob) if (raw_lob is not None and pd.notna(raw_lob)) else None

                        freq_col = next(
                            (cols_lower[k] for k in ['freq_cluster_mhz', 'freq_raw_mhz', 'freq', 'frequency'] if k in cols_lower),
                            None
                        )

                        # Inside the row loop:
                        raw_freq = pd.to_numeric(row[freq_col], errors='coerce') if freq_col else None
                        freq_val = float(raw_freq) if (raw_freq is not None and pd.notna(raw_freq)) else None
                        if not is_rabbit_file and freq_val is not None:
                            chosen_color = get_frequency_color(freq_val)

                        features[current_date].setdefault(label, []).append({
                            "lat": lat, "lon": lon, "lob": lob_val, "freq": freq_val,
                            "normalized_minutes": calc_min, "time_label": time_str,
                            "color": chosen_color, "is_rabbit": is_rabbit_file
                        })

                        updated_tracks.add(label)
                        added_count += 1
                    except Exception:
                        skipped_count += 1

            else:
                # Plain .txt file: parse each line using the same chat command syntax
                for line in decoded_text.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    c_match = re.search(r'(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)', line)
                    t_match = re.search(r'time\s*=\s*(\d{1,2})[:_]?(\d{2})', line, re.IGNORECASE)
                    if not c_match or not t_match:
                        skipped_count += 1
                        continue

                    calc_min = int(t_match.group(1)) * 60 + int(t_match.group(2))
                    if calc_min < day_min or calc_min > day_max:
                        skipped_count += 1
                        continue

                    lat, lon = float(c_match.group(1)), float(c_match.group(2))
                    time_str = f"{int(t_match.group(1)):02d}:{int(t_match.group(2)):02d}"
                    n_match = re.search(r'name\s*=\s*(?:"([^"]+)"|([^\s]+))', line, re.IGNORECASE)
                    label = (n_match.group(1) or n_match.group(2)).strip() if n_match else f"TXT-Sensor-{len(features[current_date]) + 1}"
                    col_match = re.search(r'color\s*=\s*([^\s]+)', line, re.IGNORECASE)
                    raw_col = col_match.group(1).strip().lower() if col_match else "darkgreen"
                    chosen_color = raw_col if raw_col in valid_folium_colors else "darkgreen"
                    l_match = re.search(r'lob\s*=\s*(\d+(?:\.\d+)?)', line, re.IGNORECASE)
                    lob_val = float(l_match.group(1)) if l_match else None

                    features[current_date].setdefault(label, []).append({
                        "lat": lat, "lon": lon, "lob": lob_val,
                        "normalized_minutes": calc_min, "time_label": time_str, "color": chosen_color
                    })
                    updated_tracks.add(label)
                    added_count += 1

            for lbl in updated_tracks:
                features[current_date][lbl] = sorted(features[current_date][lbl], key=lambda x: x["normalized_minutes"])

            # ─── 3. UPDATE RABBIT VS SENSOR SUMMARY COUNTS ─────────────────
            if added_count > 0:
                rabbit_tracks = [
                    t for t in updated_tracks
                    if any(n.get("is_rabbit") for n in features[current_date].get(t, []))
                    or any(k in t.lower() for k in ["rabbit", "events_list", "eventslist"])
                ]
                sensor_tracks = [t for t in updated_tracks if t not in rabbit_tracks]

                summary_parts = []
                if rabbit_tracks:
                    summary_parts.append(f"**{len(rabbit_tracks)}** rabbit(s)")
                if sensor_tracks:
                    summary_parts.append(f"**{len(sensor_tracks)}** sensor(s)")

                bot_response = (
                    f"✅ Imported **{added_count}** coordinate point(s) across {' and '.join(summary_parts)} "
                    f"(`{', '.join(sorted(updated_tracks))}`) onto **{current_date}**."
                )
                if skipped_count > 0:
                    bot_response += f"\n\n⚠️ Skipped **{skipped_count}** row(s) due to missing fields or timestamps outside **{current_date}**'s slider range."
            else:
                min_h, min_m = day_min // 60, day_min % 60
                max_h, max_m = day_max // 60, day_max % 60
                bot_response = (
                    f"❌ No valid coordinates imported from **{upload_filename}**.\n"
                    f"Ensure timestamps fall within **{current_date}**'s active window (`{min_h:02d}:{min_m:02d}` – `{max_h:02d}:{max_m:02d}`)."
                )

        except Exception as err:
            bot_response = f"❌ Error reading **{upload_filename}**: {str(err)}"

        history.append({"speaker": "assistant", "text": bot_response})
        return history, features, "", None

    # ─── CASE B: STANDARD TEXT MESSAGE ──────────────────────────────────────
    if not text or not text.strip():
        return history, features, text, None

    user_msg = text.strip()
    history.append({"speaker": "user", "text": user_msg})

    delete_match = re.search(r'delete\s*=\s*(?:"([^"]+)"|([^\s]+))', user_msg, re.IGNORECASE)
    if delete_match:
        target_to_delete = (delete_match.group(1) or delete_match.group(2)).strip()
        time_match_del = re.search(r'time\s*=\s*(\d{1,2})[:_]?(\d{2})', user_msg, re.IGNORECASE)

        if target_to_delete.lower() == 'all':
            features[current_date] = {}
            bot_response = f"🗑️ **Cleared all custom coordinates** and tracks plotted on **{current_date}**."
        elif target_to_delete in features[current_date]:
            if time_match_del:
                target_time_str = f"{int(time_match_del.group(1)):02d}:{int(time_match_del.group(2)):02d}"
                nodes = features[current_date][target_to_delete]
                updated_nodes = [n for n in nodes if n.get("time_label") != target_time_str]
                if len(updated_nodes) < len(nodes):
                    if not updated_nodes:
                        del features[current_date][target_to_delete]
                        bot_response = f"🗑️ Removed final node at **{target_time_str}** from **{target_to_delete}**. Track deleted."
                    else:
                        features[current_date][target_to_delete] = updated_nodes
                        bot_response = f"🗑️ Removed coordinate node at **{target_time_str}** from track **{target_to_delete}**."
                else:
                    bot_response = f"❌ Found track **{target_to_delete}**, but no coordinate point exists at **{target_time_str}**."
            else:
                del features[current_date][target_to_delete]
                bot_response = f"🗑️ Removed entire track **{target_to_delete}** from the map context."
        else:
            bot_response = f"❌ Track **'{target_to_delete}'** not found on **{current_date}**."

        history.append({"speaker": "assistant", "text": bot_response})
        return history, features, "", None

    coord_match = re.search(r'(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)', user_msg)
    name_match = re.search(r'name\s*=\s*(?:"([^"]+)"|([^\s]+))', user_msg, re.IGNORECASE)
    lob_match = re.search(r'lob\s*=\s*(\d+(?:\.\d+)?)', user_msg, re.IGNORECASE)
    time_match = re.search(r'time\s*=\s*(\d{1,2})[:_]?(\d{2})', user_msg, re.IGNORECASE)
    color_match = re.search(r'color\s*=\s*([^\s]+)', user_msg, re.IGNORECASE)

    label = (name_match.group(1) or name_match.group(2)).strip() if name_match else f"AI-Sensor-{len(features[current_date]) + 1}"
    lob_val = float(lob_match.group(1)) if lob_match else None
    chosen_color = 'darkgreen'
    unrecognized_color_entered = False

    if color_match:
        input_color = color_match.group(1).strip().lower()
        if input_color in valid_folium_colors:
            chosen_color = input_color
        else:
            unrecognized_color_entered = True

    if not coord_match:
        bot_response = "❌ Could not parse coordinates. Use: `35.21, -116.64 name=\"Sensor X\" time=14:30` or upload a `.csv`/`.txt` file with 📎."
    elif not time_match:
        bot_response = "⚠️ **Missing Required Timestamp!** Provide track time: `time=HH:MM`"
    else:
        lat, lon = float(coord_match.group(1)), float(coord_match.group(2))
        calculated_minutes = int(time_match.group(1)) * 60 + int(time_match.group(2))
        time_str = f"{int(time_match.group(1)):02d}:{int(time_match.group(2)):02d}"

        if calculated_minutes < day_min or calculated_minutes > day_max:
            min_h, min_m = day_min // 60, day_min % 60
            max_h, max_m = day_max // 60, day_max % 60
            bot_response = (
                f"❌ **Timeline Range Error!** Time (**{time_str}**) falls outside **{current_date}**'s "
                f"allowed window (`{min_h:02d}:{min_m:02d}` to `{max_h:02d}:{max_m:02d}`)."
            )
        else:
            features[current_date].setdefault(label, []).append({
                "lat": lat, "lon": lon, "lob": lob_val,
                "normalized_minutes": calculated_minutes, "time_label": time_str, "color": chosen_color
            })
            features[current_date][label] = sorted(features[current_date][label], key=lambda x: x["normalized_minutes"])

            node_count = len(features[current_date][label])
            bot_response = (
                f"📈 Extended track **{label}** using color **'{chosen_color}'**."
                if node_count > 1 else
                f"📍 Added point to **{label}** at {time_str} with theme color **'{chosen_color}'**."
            )
            if unrecognized_color_entered:
                bot_response += (
                    f"\n\n⚠️ **Note:** The entered color `'{input_color}'` is unrecognized. "
                    f"Defaulted to **'darkgreen'**. Supported choices:\n`{', '.join(valid_folium_colors)}`"
                )
            if lob_val is not None:
                bot_response += f"\n\nOrientation Line of Bearing set to **{lob_val}°**."

    history.append({"speaker": "assistant", "text": bot_response})
    return history, features, "", None


@app.callback(
    Output('chat-conversation-area', 'children'),
    [Input('chat-history-store', 'data'),
     Input('dark-mode-btn', 'n_clicks')]
)
def render_chat_log(history, dark_clicks):
    is_dark = (dark_clicks or 0) % 2 == 1

    if not history:
        placeholder_color = '#adb5bd' if is_dark else '#6c757d'
        return [html.Div(
            "Hello! Provide standard coordinate sequences to render dynamic markers.",
            style={'color': placeholder_color, 'fontStyle': 'italic'}
        )]
    
    elements = []
    for msg in history:
        is_user = msg['speaker'] == 'user'
        
        if is_dark:
            bg_color = '#3a3b3c' if is_user else '#1e3a5f'
            text_color = '#f8f9fa'
        else:
            bg_color = '#e2e3e5' if is_user else '#d1ecf1'
            text_color = '#212529'
            
        align = 'flex-end' if is_user else 'flex-start'
        elements.append(html.Div(
            dcc.Markdown(msg['text']),
            style={
                'alignSelf': align,
                'backgroundColor': bg_color,
                'color': text_color,
                'padding': '8px 12px',
                'borderRadius': '6px',
                'margin': '4px 0',
                'maxWidth': '85%',
                'wordBreak': 'break-word'
            }
        ))
        
    return html.Div(elements, style={'display': 'flex', 'flexDirection': 'column'})

@app.callback(
    [Output('time-slider', 'max'), 
     Output('time-slider', 'marks'), 
     Output('time-slider', 'value')],
    [Input('date-tabs', 'value'),
     Input('play-interval', 'n_intervals')],
    [State('slider-mode-toggle', 'value'),
     State('time-slider', 'value'),
     State('active-handle-store', 'data'),
     State('dark-mode-btn', 'n_clicks')]
)
def update_slider_mechanics(selected_date, n_intervals, mode, current_val, store_data, dark_clicks):
    is_dark = (dark_clicks or 0) % 2 == 1
    ctx = callback_context
    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0] if ctx.triggered else None
    total_range, marks = lookup_timeline_scale(selected_date, is_dark=is_dark)
    
    if trigger_id == 'date-tabs' or trigger_id is None or trigger_id == '':
        return total_range, marks, (0 if mode == 'SINGLE' else [0, total_range])
        
    if trigger_id == 'play-interval':
        if mode == 'SINGLE':
            curr = int(current_val) if isinstance(current_val, (int, float)) else 0
            return total_range, marks, min(curr + 1, total_range)
        else:
            if isinstance(current_val, list) and len(current_val) == 2:
                low_handle = int(current_val[0])
                high_handle = int(current_val[1])
                active_handle = (store_data or {}).get('handle', 0)

                if active_handle == 0:
                    low_handle = min(low_handle + 1, high_handle)
                else:
                    high_handle = min(high_handle + 1, total_range)
                return total_range, marks, [low_handle, high_handle]
            return total_range, marks, [0, total_range]
        
    return total_range, marks, (0 if mode == 'SINGLE' else [0, total_range])

@app.callback(
    Output('folium-map', 'srcDoc'),
    [Input('date-tabs', 'value'),
     Input('dark-mode-btn', 'n_clicks')]
)
def update_map(selected_date, dark_clicks):
    is_dark = (dark_clicks or 0) % 2 == 1
    legend_bg = "#212529" if is_dark else "white"
    legend_fg = "#f8f9fa" if is_dark else "black"
    legend_border = "#555" if is_dark else "grey"

    # Keyless OpenStreetMap tiles for both themes; dark mode applies a clean CSS invert filter to the map tiles only
    my_map = folium.Map(
        location=[35.219, -116.648],
        zoom_start=12,
        tiles="OpenStreetMap",
        prefer_canvas=True
    )

    dark_tile_css = (
        ".leaflet-tile-pane { filter: invert(100%) hue-rotate(180deg) brightness(95%) contrast(90%); }"
        if is_dark else ""
    )

    remove_scrollbars_css = f"""
    <style>
        html, body {{ overflow: hidden !important; margin: 0 !important; padding: 0 !important; width: 100% !important; height: 100% !important; }}
        ::-webkit-scrollbar {{ display: none !important; }}
        {dark_tile_css}
    </style>
    """
    my_map.get_root().html.add_child(folium.Element(remove_scrollbars_css))

    live_listener_js = f"""
    <div id="dynamic-legend" style="position: fixed; bottom: 50px; left: 50px; width: 165px; background-color: {legend_bg}; color: {legend_fg}; border: 2px solid {legend_border}; z-index: 9999; font-size: 13px; padding: 10px; font-family: sans-serif; box-shadow: 2px 2px 5px rgba(0,0,0,0.3);">
        <b>Legend ({selected_date})</b><br><span style="color: gray;">Loading...</span>
    </div>
    <script>
        var layerRegistry = {{}};
        var layerControl = null;
        var hasCentered = false;

        function getMap() {{
            var maps = Object.keys(window).filter(function(k) {{ return k.startsWith('map_'); }});
            return maps.length > 0 ? window[maps] : null;
        }}

        function renderPayload(payload) {{
            var mapObj = getMap();
            if (!mapObj || !payload || !payload.layers) return;

            if (!layerControl) {{
                layerControl = L.control.layers(null, {{}}).addTo(mapObj);
                var savedCenter = localStorage.getItem('dash_map_center');
                var savedZoom = localStorage.getItem('dash_map_zoom');
                if (savedCenter && savedZoom) {{
                    mapObj.setView(JSON.parse(savedCenter), parseInt(savedZoom), {{animate: false}});
                    hasCentered = true;
                }}
                mapObj.on('moveend zoomend', function() {{
                    localStorage.setItem('dash_map_center', JSON.stringify(mapObj.getCenter()));
                    localStorage.setItem('dash_map_zoom', mapObj.getZoom());
                }});
            }}

            var hiddenLayers = JSON.parse(localStorage.getItem('dash_hidden_layers') || '[]');
            var activeNames = payload.layers.map(function(l) {{ return l.name; }});

            Object.keys(layerRegistry).forEach(function(existingName) {{
                if (!activeNames.includes(existingName)) {{
                    layerControl.removeLayer(layerRegistry[existingName]);
                    mapObj.removeLayer(layerRegistry[existingName]);
                    delete layerRegistry[existingName];
                }}
            }});

            var legendRows = [];
            var seenLegend = {{}};

            payload.layers.forEach(function(layer) {{
                if (!layerRegistry[layer.name]) {{
                    var fg = L.layerGroup();
                    layerRegistry[layer.name] = fg;
                    layerControl.addOverlay(fg, layer.name);
                    if (!hiddenLayers.includes(layer.name)) {{
                        fg.addTo(mapObj);
                    }}
                }} else {{
                    layerRegistry[layer.name].clearLayers();
                }}

                var targetGroup = layerRegistry[layer.name];

                if (layer.points && layer.points.length > 0) {{
                    if (!hasCentered) {{
                        mapObj.setView(layer.points, 12, {{animate: false}});
                        hasCentered = true;
                    }}
                    if (layer.points.length > 1) {{
                        L.polyline(layer.points, {{color: layer.color, weight: 3, opacity: 0.8, dashArray: '5,5'}}).addTo(targetGroup);
                    }}
                    var head = layer.points[layer.points.length - 1];
                    L.circleMarker(head, {{
                        radius: layer.is_rabbit ? 8 : 7,
                        color: layer.color,
                        fillColor: layer.color,
                        fillOpacity: 0.9
                    }}).bindPopup(layer.popup).addTo(targetGroup);

                    if (layer.cones) {{
                        layer.cones.forEach(function(coneLine) {{
                            L.polyline(coneLine, {{color: layer.color, weight: 2, opacity: 0.65}}).addTo(targetGroup);
                        }});
                    }}
                    legendRows.push('<i style="background:' + layer.color + '; width:10px; height:10px; display:inline-block; margin-right:6px;"></i>' + layer.name);
                }}

                if (layer.points && layer.points.length > 0 && layer.is_rabbit) {{
                    var cleanName = String(layer.name).trim();
                }}
            }});

            if (payload.freq_legend) {{
                Object.keys(payload.freq_legend).sort().forEach(function(fLabel) {{
                    var cleanFreq = String(fLabel).trim();
                    if (!seenLegend[cleanFreq]) {{
                        seenLegend[cleanFreq] = true;
                        var fColor = payload.freq_legend[fLabel];
                        legendRows.push(
                            '<i style="background:' + fColor +
                            '; width:10px; height:10px; display:inline-block; margin-right:6px;"></i>' +
                            cleanFreq
                        );
                    }}
                }});
            }}
            document.getElementById('dynamic-legend').innerHTML =
                '<b>Legend (' + payload.date + ')</b><br>' + legendRows.join('<br>');
        }}

        window.addEventListener('message', function(event) {{
            if (event.data && event.data.type === 'UPDATE_MAP_LAYERS') {{
                window._latestPayload = event.data.payload;
                renderPayload(event.data.payload);
            }}
        }});

        window.addEventListener('load', function() {{
            var mapObj = getMap();
            if (mapObj) {{
                mapObj.on('overlayremove', function(e) {{
                    var cur = JSON.parse(localStorage.getItem('dash_hidden_layers') || '[]');
                    if (!cur.includes(e.name)) {{
                        cur.push(e.name);
                        localStorage.setItem('dash_hidden_layers', JSON.stringify(cur));
                    }}
                }});
                mapObj.on('overlayadd', function(e) {{
                    var cur = JSON.parse(localStorage.getItem('dash_hidden_layers') || '[]');
                    localStorage.setItem('dash_hidden_layers', JSON.stringify(cur.filter(function(x) {{ return x !== e.name; }})));
                }});
            }}
            if (window._latestPayload) {{
                renderPayload(window._latestPayload);
            }}
        }});
    </script>
    """
    my_map.get_root().html.add_child(folium.Element(live_listener_js))
    return my_map.get_root().render()

FREQ_COLOR_PALETTE = [
    "#ff7f0e",  # Vivid Orange
    "#2ca02c",  # Emerald Green
    "#9467bd",  # Purple
    "#17becf",  # Cyan
    "#e377c2",  # Pink/Magenta
    "#bcbd22",  # Olive/Lime
    "#ffbb78",  # Amber
    "#98df8a",  # Mint
    "#c5b0d5",  # Lavender
    "#f7b6d2",  # Rose
]

def get_frequency_color(freq_val):
    if freq_val is None or pd.isna(freq_val):
        return "#808080"
    bucket = int(round(float(freq_val) * 10))
    return FREQ_COLOR_PALETTE[bucket % len(FREQ_COLOR_PALETTE)]

@app.callback(
    Output('live-map-payload', 'data'),
    [Input('date-tabs', 'value'),
     Input('time-slider', 'value'),
     Input('bot-features-store', 'data')]
)
def compute_live_map_data(selected_date, slider_range_window, bot_features):
    if slider_range_window is None:
        return {"date": selected_date, "layers": []}

    day_cache = GLOBAL_DATA_CACHE[selected_date]
    start_min = day_cache["min_minute"]

    if isinstance(slider_range_window, list) and len(slider_range_window) >= 2:
        min_cutoff = start_min + int(slider_range_window[0])
        max_cutoff = start_min + int(slider_range_window[1])
    else:
        val = slider_range_window[0] if isinstance(slider_range_window, list) else slider_range_window
        min_cutoff = start_min
        max_cutoff = start_min + int(val)

    use_sensors = selected_date in ["18JUL", "21JUL", "23JUL", "24JUL"]
    layers_def = [
        ("Rabbit 1", "blue", day_cache["r1_rabbit"], True),
        ("Rabbit 2", "red", day_cache["r2_rabbit"], True),
        ("Sensor 10" if use_sensors else "Raven 1", "orange", day_cache["v1_sensor"], False),
        ("Sensor 11" if use_sensors else "Raven 2", "green", day_cache["v2_sensor"], False),
        ("Sensor 12" if use_sensors else "Raven 3", "purple", day_cache["v3_sensor"], False),
    ]

    output_layers = []
    freq_legend_entries = {}

    for name, default_color, parsed_list, is_rabbit in layers_def:
        timed_pts, raw_lob, latest_min, latest_freq = [], None, None, None
        for item in (parsed_list or []):
            df, lt, ln, lb, fq = item
            if df.empty:
                continue
            sliced = df.loc[(df['normalized_minutes'] >= min_cutoff) & (df['normalized_minutes'] <= max_cutoff)]
            if not sliced.empty:
                # Pair every coordinate with its timestamp so multi-file tracks stay strictly chronological
                for m_val, lat_v, lon_v in zip(
                    sliced['normalized_minutes'].to_numpy(),
                    sliced[lt].to_numpy(),
                    sliced[ln].to_numpy()
                ):
                    timed_pts.append((float(m_val), float(lat_v), float(lon_v)))

                last_row_min = int(sliced['normalized_minutes'].iloc[-1])
                if latest_min is None or last_row_min >= latest_min:
                    latest_min = last_row_min
                    if lb and not sliced[lb].dropna().empty:
                        raw_lob = float(sliced[lb].dropna().iloc[-1])
                    if fq and not sliced[fq].dropna().empty:
                        latest_freq = float(sliced[fq].dropna().iloc[-1])

        # Sort chronologically across all files for this sensor/rabbit
        timed_pts.sort(key=lambda x: x)
        pts = [[lat_v, lon_v] for _, lat_v, lon_v in timed_pts]

        if pts:
            # Use a fixed step size (every 2nd point) instead of a shifting divisor so existing trail geometry never morphs
            if len(pts) > 400:
                pts = pts[::2] + ([pts[-1]] if len(pts) % 2 == 0 else [])
            head = pts[-1]
            time_str = f"{(latest_min // 60) % 24:02d}:{latest_min % 60:02d}" if latest_min is not None else "N/A"
            cones = []

            if is_rabbit:
                layer_color = default_color
                popup_html = (
                    f"<b>{name}</b><br>"
                    f"Time: {time_str}<br>"
                    f"Lat: {head[0]:.6f}<br>"
                    f"Lon: {head[1]:.6f}"
                )
            else:
                layer_color = get_frequency_color(latest_freq)
                freq_label = f"{latest_freq:.2f} MHz" if latest_freq is not None else "Unknown Freq"
                freq_legend_entries[freq_label] = layer_color

                if raw_lob is not None:
                    for offset in (-25.0, 25.0):
                        rad = math.radians(raw_lob + offset)
                        cones.append([head, [head[0] + 0.08 * math.cos(rad), head[1] + 0.08 * math.sin(rad)]])
                lob_text = f"{raw_lob}°" if raw_lob is not None else "N/A"
                popup_html = (
                    f"<b>{name}</b><br>"
                    f"Time: {time_str}<br>"
                    f"Frequency: {freq_label}<br>"
                    f"LOB Abs Degree: {lob_text}<br>"
                    f"Lat: {head[0]:.6f}<br>"
                    f"Lon: {head[1]:.6f}"
                )

            output_layers.append({
                "name": name,
                "color": layer_color,
                "is_rabbit": is_rabbit,
                "points": pts,
                "cones": cones,
                "popup": popup_html,
                "legend_label": name if is_rabbit else None
            })

    if bot_features and selected_date in bot_features:
        for b_lbl, nodes in bot_features[selected_date].items():
            vis = [n for n in nodes if min_cutoff <= n.get("normalized_minutes", 0) <= max_cutoff]
            if not vis:
                continue
            last = vis[-1]
            pts = [[n["lat"], n["lon"]] for n in vis]
            is_rabbit_track = (
                bool(last.get("is_rabbit"))
                or any(k in b_lbl.lower() for k in ["rabbit", "events_list", "eventslist"])
            )

            valid_lobs = [float(n["lob"]) for n in vis if n.get("lob") is not None]
            latest_lob = valid_lobs[-1] if valid_lobs else None
            cones = []

            if is_rabbit_track:
                popup_html = (
                    f"<b>{b_lbl}</b><br>"
                    f"Time: {last.get('time_label', 'N/A')}<br>"
                    f"Lat: {last['lat']:.6f}<br>"
                    f"Lon: {last['lon']:.6f}"
                )
            else:
                if latest_lob is not None:
                    for offset in (-25.0, 25.0):
                        rad = math.radians(latest_lob + offset)
                        cones.append([
                            [last["lat"], last["lon"]],
                            [last["lat"] + 0.08 * math.cos(rad), last["lon"] + 0.08 * math.sin(rad)]
                        ])
                lob_text = f"{latest_lob}°" if latest_lob is not None else "N/A"
                popup_html = (
                    f"<b>{b_lbl}</b><br>"
                    f"Time: {last.get('time_label', 'N/A')}<br>"
                    f"LOB Abs Degree: {lob_text}<br>"
                    f"Lat: {last['lat']:.6f}<br>"
                    f"Lon: {last['lon']:.6f}"
                )

            output_layers.append({
                "name": b_lbl,
                "color": last.get("color", "darkgreen"),
                "is_rabbit": is_rabbit_track,
                "points": pts,
                "cones": cones,
                "popup": popup_html
            })

            valid_freqs = [float(n["freq"]) for n in vis if n.get("freq") is not None]
            latest_freq = valid_freqs[-1] if valid_freqs else None

            if not is_rabbit_track and latest_freq is not None:
                track_color = get_frequency_color(latest_freq)
                freq_label = f"{latest_freq:.2f} MHz"
                freq_legend_entries[freq_label] = track_color
            else:
                track_color = last.get("color", "darkgreen")
                freq_label = "N/A"

    return {"date": selected_date, "layers": output_layers}

@app.callback(
    Output('postmessage-bridge', 'children'),
    [Input('live-map-payload', 'data'),
     Input('folium-map', 'srcDoc')]
)
def push_payload_to_iframe(payload, _):
    if not payload or not payload.get("layers"):
        return ""
    encoded = json.dumps(payload)
    return html.Iframe(
        srcDoc=f"""
        <script>
            (function() {{
                var data = {encoded};
                var attempts = 0;
                var timer = setInterval(function() {{
                    attempts++;
                    var mapFrame = window.parent.document.getElementById('folium-map');
                    if (mapFrame && mapFrame.contentWindow && typeof mapFrame.contentWindow.renderPayload === 'function') {{
                        mapFrame.contentWindow.postMessage({{type: 'UPDATE_MAP_LAYERS', payload: data}}, '*');
                        clearInterval(timer);
                    }} else if (attempts > 40) {{
                        clearInterval(timer);
                    }}
                }}, 50);
            }})();
        </script>
        """,
        style={'display': 'none'}
    )

if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=8055)