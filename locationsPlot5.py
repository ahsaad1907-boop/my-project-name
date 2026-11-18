import os
import glob
import re
import math
import pandas as pd
import folium
from dash import Dash, dcc, html, Input, Output, State, callback_context

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
            return pd.DataFrame(), None, None, None
            
        lob_col = None
        for col in df.columns:
            if "lob" in col.lower() and "deg" in col.lower():
                lob_col = col
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
                df['normalized_minutes'] = (
                    int(match_fn.group(1)) * 60 + int(match_fn.group(2))
                )
            else:
                return pd.DataFrame(), None, None, None
        else:
            df['normalized_minutes'] = df[time_col].apply(parse_time_to_minutes)

        df[lat_col] = pd.to_numeric(df[lat_col], errors="coerce")
        df[lon_col] = pd.to_numeric(df[lon_col], errors="coerce")
        df.dropna(subset=[lat_col, lon_col, 'normalized_minutes'], inplace=True)
        
        if lob_col:
            df[lob_col] = pd.to_numeric(df[lob_col], errors="coerce")
            
        return df, lat_col, lon_col, lob_col
    except Exception:
        return pd.DataFrame(), None, None, None


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
            df, lat_c, lon_c, lob_c = packed
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


def lookup_timeline_scale(selected_date):
    day_cache = GLOBAL_DATA_CACHE[selected_date]
    m_start = day_cache["min_minute"]
    m_end = day_cache["max_minute"]
    
    total_range = m_end - m_start
    total_range = max(1, total_range)
    
    marks = {}
    for step in range(0, total_range + 1, 60):
        total_m = m_start + step
        h = total_m // 60
        m = total_m % 60
        marks[step] = f"{h:02d}:{m:02d}"
        
    h_end = m_end // 60
    m_end_inner = m_end % 60
    marks[total_range] = f"{h_end:02d}:{m_end_inner:02d}"
    
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
    
    html.H1(
        "Sensor Tracking Dashboard", 
        style={
            'textAlign': 'center', 'fontFamily': 'sans-serif', 'margin': '10px 0'
        }
    ),
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
                html.Label("Slider Mode:", style={'fontWeight': 'bold', 'fontFamily': 'sans-serif', 'marginRight': '6px'}),
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
                dcc.Input(
                    id='chat-user-input', type='text', 
                    placeholder='e.g. 35.21, -116.64 name="Sensor X" time=14:30 color=red lob=95',
                    style={'flex': '1', 'padding': '0px', 'border': '1px solid #ccc', 'borderRadius': '4px'},
                    n_submit=0
                ),
                html.Button(
                    "Send", id='chat-send-btn', n_clicks=0,
                    style={'padding': '8px 12px', 'marginLeft': '5px', 'backgroundColor': '#28a745', 'color': 'white', 'border': 'none', 'borderRadius': '4px', 'cursor': 'pointer'}
                )
            ], style={'display': 'flex', 'padding': '10px', 'backgroundColor': '#fff', 'borderTop': '1px solid #ddd'}),
            
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
     Input('date-tabs', 'value')]
)
def render_dynamic_slider_component(mode, selected_date):
    total_range, marks = lookup_timeline_scale(selected_date)
    
    if mode == 'SINGLE':
        return dcc.Slider(
            id='time-slider', 
            min=0, 
            max=total_range, 
            step=1, 
            value=0,
            marks=marks
        )
    else:
        return dcc.RangeSlider(
            id='time-slider', 
            min=0, 
            max=total_range, 
            step=1, 
            value=[0, total_range],
            marks=marks
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
     Output('chat-user-input', 'value')],
    [Input('chat-send-btn', 'n_clicks'),
     Input('chat-user-input', 'n_submit'),
     Input('chat-reset-btn', 'n_clicks')],
    [State('chat-user-input', 'value'),
     State('chat-history-store', 'data'),
     State('bot-features-store', 'data'),
     State('date-tabs', 'value')]
)
def process_chatbot_intelligence(clicks, sub, reset_clicks, text, history, features, current_date):
    ctx = callback_context
    if not ctx.triggered:
        return history, features, text

    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0] if ctx.triggered else None

    if trigger_id == 'chat-reset-btn':
        return [], features, ""

    if not text:
        return history, features, text

    user_msg = text.strip()
    history = history or []
    features = features or {}
    
    if current_date not in features:
        features[current_date] = {}

    history.append({"speaker": "user", "text": user_msg})

    delete_match = re.search(r'delete\s*=\s*([^\s]+)', user_msg, re.IGNORECASE)
    if delete_match:
        target_to_delete = delete_match.group(1).strip()
        time_match_del = re.search(r'time\s*=\s*(\d{1,2})[:_]?(\d{2})', user_msg, re.IGNORECASE)
        
        if target_to_delete.lower() == 'all':
            features[current_date] = {}
            bot_response = f"🗑️ **Cleared all custom coordinates** on **{current_date}**."
        elif target_to_delete in features[current_date]:
            if time_match_del:
                del_hour = int(time_match_del.group(1))
                del_minute = int(time_match_del.group(2))
                target_time_str = f"{del_hour:02d}:{del_minute:02d}"
                
                nodes = features[current_date][target_to_delete]
                original_count = len(nodes)
                updated_nodes = [node for node in nodes if node.get("time_label") != target_time_str]
                
                if len(updated_nodes) < original_count:
                    if not updated_nodes:
                        del features[current_date][target_to_delete]
                        bot_response = f"🗑️ Removed final coordinate point from **{target_to_delete}**."
                    else:
                        features[current_date][target_to_delete] = updated_nodes
                        bot_response = f"🗑️ Removed point at **{target_time_str}** from **{target_to_delete}**."
                else:
                    bot_response = f"❌ No point found at **{target_time_str}**."
            else:
                del features[current_date][target_to_delete]
                bot_response = f"🗑️ Removed entire track **{target_to_delete}**."
        else:
            bot_response = f"❌ Track **'{target_to_delete}'** not found on **{current_date}**."
            
        history.append({"speaker": "assistant", "text": bot_response})
        return history, features, ""

    coord_pattern = r'(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)'
    coord_match = re.search(coord_pattern, user_msg)
    
    name_match = re.search(r'name\s*=\s*(?:["“”]([^"“”]+)["“”]|([^\s]+))', user_msg, re.IGNORECASE)
    lob_match = re.search(r'lob\s*=\s*(\d+)', user_msg, re.IGNORECASE)
    time_match = re.search(r'time\s*=\s*(\d{1,2})[:_]?(\d{2})', user_msg, re.IGNORECASE)
    color_match = re.search(r'color\s*=\s*([^\s]+)', user_msg, re.IGNORECASE)
    
    if name_match:
        label = name_match.group(1) if name_match.group(1) is not None else name_match.group(2)
        label = label.strip().strip('"').strip('“').strip('”')
    else:
        label = f"AI-Sensor-{len(features[current_date]) + 1}"
        
    lob_val = float(lob_match.group(1)) if lob_match else None
    
    valid_folium_colors = [
        'red', 'blue', 'green', 'purple', 'orange', 'darkred', 'lightred', 'beige', 
        'darkblue', 'darkgreen', 'cadetblue', 'pink', 'lightblue', 'lightgreen', 
        'gray', 'black', 'lightgray'
    ]
    
    unrecognized_color_entered = False
    chosen_color = 'darkgreen'
    
    if color_match:
        input_color = color_match.group(1).strip().lower()
        if input_color in valid_folium_colors:
            chosen_color = input_color
        else:
            unrecognized_color_entered = True

    if not coord_match:
        bot_response = "❌ Could not parse coordinates. Use: `35.219, -116.648`"
    elif not time_match:
        bot_response = "⚠️ **Missing Timestamp!** Provide a track time: `time=HH:MM`"
    else:
        lat = float(coord_match.group(1))
        lon = float(coord_match.group(2))
        
        target_hour = int(time_match.group(1))
        target_minute = int(time_match.group(2))
        calculated_minutes = target_hour * 60 + target_minute
        time_str = f"{target_hour:02d}:{target_minute:02d}"

        day_cache = GLOBAL_DATA_CACHE[current_date]
        day_min = day_cache["min_minute"]
        day_max = day_cache["max_minute"]
        
        if calculated_minutes < day_min or calculated_minutes > day_max:
            min_h, min_m = day_min // 60, day_min % 60
            max_h, max_m = day_max // 60, day_max % 60
            bot_response = f"❌ **Timeline Error!** Window: `{min_h:02d}:{min_m:02d}` to `{max_h:02d}:{max_m:02d}`."
        else:
            new_node = {
                "lat": lat, "lon": lon, "lob": lob_val,
                "normalized_minutes": calculated_minutes,
                "time_label": time_str, "color": chosen_color 
            }
            if label not in features[current_date]:
                features[current_date][label] = []
            features[current_date][label].append(new_node)
            features[current_date][label] = sorted(features[current_date][label], key=lambda x: x["normalized_minutes"])
            
            node_count = len(features[current_date][label])
            if node_count > 1:
                bot_response = f"📈 Extended track **{label}** using color **'{chosen_color}'**."
            else:
                bot_response = f"📍 Added point to **{label}** at {time_str} with theme color **'{chosen_color}'**."
                
            if unrecognized_color_entered:
                bot_response += (
                    f"\n\n⚠️ **Note:** The entered color `'{input_color}'` is unrecognized. "
                    f"Defaulted to **'darkgreen'**. Try using one of these supported choices next time:\n"
                    f"`{', '.join(valid_folium_colors)}`"
                )
                
            if lob_val is not None:
                bot_response += f"\n\nOrientation Line of Bearing set to **{lob_val}°**."

    history.append({"speaker": "assistant", "text": bot_response})
    return history, features, ""


@app.callback(
    Output('chat-conversation-area', 'children'),
    Input('chat-history-store', 'data')
)
def render_chat_log(history):
    if not history:
        return [html.Div("Hello! Provide standard coordinate sequences to render dynamic geo-markers directly on the map viewport canvas layer.", style={'color': '#6c757d', 'fontStyle': 'italic'})]
    
    elements = []
    for msg in history:
        is_user = msg['speaker'] == 'user'
        bg_color = '#e2e3e5' if is_user else '#d1ecf1'
        align = 'flex-end' if is_user else 'flex-start'
        
        elements.append(html.Div(
            dcc.Markdown(msg['text']),
            style={
                'alignSelf': align, 'backgroundColor': bg_color, 'padding': '8px 12px',
                'borderRadius': '6px', 'margin': '4px 0', 'maxWidth': '85%',
                'wordBreak': 'break-word', 'boxShadow': '1px 1px 2px rgba(0,0,0,0.05)'
            }
        ))
        
    elements.append(html.Iframe(
        srcDoc="""
        <script>
            setTimeout(function() {
                var target = window.parent.document.getElementById('chat-conversation-area');
                if (target) {
                    target.scrollTop = target.scrollHeight;
                }
            }, 20);
        </script>
        """,
        style={'display': 'none'}
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
     State('active-handle-store', 'data')]
)
def update_slider_mechanics(selected_date, n_intervals, mode, current_val, store_data):
    ctx = callback_context
    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0] if ctx.triggered else None
    total_range, marks = lookup_timeline_scale(selected_date)
    
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
     Input('time-slider', 'value'),
     Input('bot-features-store', 'data')]
)
def update_map(selected_date, slider_range_window, bot_features):
    if slider_range_window is None:
        return ""
    try:
        my_map = None
        day_cache = GLOBAL_DATA_CACHE[selected_date]
        start_minute_offset = day_cache["min_minute"]
        
        if isinstance(slider_range_window, list):
            min_cutoff = start_minute_offset + int(slider_range_window[0])
            max_cutoff = start_minute_offset + int(slider_range_window[1])
        else:
            min_cutoff = start_minute_offset
            max_cutoff = start_minute_offset + int(slider_range_window)
        
        use_sensors = selected_date in ["18JUL", "21JUL", "23JUL", "24JUL"]
        name_ch1 = "Sensor 10" if use_sensors else "Raven 1"
        name_ch2 = "Sensor 11" if use_sensors else "Raven 2"
        name_ch3 = "Sensor 12" if use_sensors else "Raven 3"
        
        layers_definition = {
            "Rabbit 1": ('blue', day_cache["r1_rabbit"], True),
            "Rabbit 2": ('red', day_cache["r2_rabbit"], True),
            name_ch1: ('orange', day_cache["v1_sensor"], False),
            name_ch2: ('green', day_cache["v2_sensor"], False),
            name_ch3: ('purple', day_cache["v3_sensor"], False)
        }
        
        active_legend_items = []
        
        for layer_name, (color, parsed_list, is_rabbit) in layers_definition.items():
            if not parsed_list:
                continue
                
            combined_points = []
            latest_lob_val = "N/A"
            raw_lob_degrees = None
            file_time_str = "N/A"
            
            for item in parsed_list:
                df, lt, ln, lb = item
                if df.empty:
                    continue
                
                mask = (df['normalized_minutes'] >= min_cutoff) & (df['normalized_minutes'] <= max_cutoff)
                sliced_df = df.loc[mask]
                
                if not sliced_df.empty:
                    combined_points.extend(sliced_df[[lt, ln]].to_numpy().tolist())
                    
                    if 'normalized_minutes' in sliced_df.columns:
                        last_mins = int(sliced_df['normalized_minutes'].iloc[-1])
                        file_time_str = f"{last_mins // 60:02d}:{last_mins % 60:02d}"
                        
                    if lb:
                        valid_lobs = sliced_df[lb].dropna()
                        if not valid_lobs.empty:
                            raw_lob_degrees = float(valid_lobs.iloc[-1])
                            latest_lob_val = f"{raw_lob_degrees}°"

            if combined_points:
                if len(combined_points) > 200:
                    combined_points = combined_points[::len(combined_points)//100]

                if my_map is None:
                    my_map = folium.Map(location=combined_points[0], zoom_start=12, prefer_canvas=True)
                
                feature_group = folium.FeatureGroup(name=layer_name)
                
                folium.PolyLine(
                    combined_points, color=color, weight=3, opacity=0.8, dash_array='5,5'
                ).add_to(feature_group)
                
                trailing_head = combined_points[-1]
                
                trailing_head = combined_points[-1]
                
                t_lat = trailing_head[0]
                t_lon = trailing_head[1]
                
                if is_rabbit:
                    popup_msg = (
                        f"<b>{layer_name}</b><br>"
                        f"Coordinates: Lat: {t_lat:.5f}, Lon: {t_lon:.5f}<br>"
                        f"Timestamp: {file_time_str}"
                    )
                    folium.Marker(location=trailing_head, popup=popup_msg, icon=folium.Icon(color=color)).add_to(feature_group)
                else:
                    popup_msg = (
                        f"<b>{layer_name}</b><br>"
                        f"Coordinates: Lat: {t_lat:.5f}, Lon: {t_lon:.5f}<br>"
                        f"Timestamp: {file_time_str}<br>"
                        f"LOB Abs Degree: {latest_lob_val}"
                    )
                    folium.CircleMarker(location=trailing_head, radius=7, color=color, fill=True, popup=popup_msg).add_to(feature_group)
                    
                    if raw_lob_degrees is not None:
                        cone_length = 0.08  
                        fov_half_angle = 25.0  
                        
                        angle_left = math.radians(raw_lob_degrees - fov_half_angle)
                        angle_right = math.radians(raw_lob_degrees + fov_half_angle)
                        
                        left_lat = t_lat + (cone_length * math.cos(angle_left))
                        left_lon = t_lon + (cone_length * math.sin(angle_left))
                        
                        right_lat = t_lat + (cone_length * math.cos(angle_right))
                        right_lon = t_lon + (cone_length * math.sin(angle_right))
                        
                        folium.PolyLine([trailing_head, [left_lat, left_lon]], color=color, weight=2, opacity=0.6).add_to(feature_group)
                        folium.PolyLine([trailing_head, [right_lat, right_lon]], color=color, weight=2, opacity=0.6).add_to(feature_group)
                
                if latest_lob_val != "N/A" and not is_rabbit:
                    folium.Marker(
                        location=[t_lat + 0.004, t_lon],
                        icon=folium.DivIcon(
                            html=f"""<div style="font-family: sans-serif; font-size: 11px; font-weight: bold; color: black; background-color: rgba(255,255,255,0.7); padding: 2px 4px; border-radius: 3px; border: 1px solid {color}; white-space: nowrap; margin-top: -12px;">{layer_name}: {latest_lob_val}</div>"""
                        )
                    ).add_to(feature_group)
                
                active_legend_items.append((layer_name, color))
                feature_group.add_to(my_map)

        if bot_features and selected_date in bot_features:
            for b_lbl, nodes in bot_features[selected_date].items():
                visible_nodes = [n for n in nodes if min_cutoff <= n.get("normalized_minutes", 0) <= max_cutoff]
                if not visible_nodes:
                    continue
                    
                most_recent_node = visible_nodes[-1]
                track_color = most_recent_node.get("color", "darkgreen")
                bot_fg = folium.FeatureGroup(name=b_lbl)
                combined_points = [[n["lat"], n["lon"]] for n in visible_nodes]
                
                if my_map is None:
                    my_map = folium.Map(location=combined_points[0], zoom_start=12, prefer_canvas=True)
                
                if len(combined_points) > 1:
                    folium.PolyLine(combined_points, color=track_color, weight=3, opacity=0.8, dash_array='5,5').add_to(bot_fg)
                
                b_lat, b_lon = most_recent_node["lat"], most_recent_node["lon"]
                b_lob, b_time = most_recent_node["lob"], most_recent_node.get("time_label", "N/A")
                
                is_bot_rabbit = "rabbit" in b_lbl.lower()
                latest_bot_lob_str = f"{b_lob}°" if b_lob is not None else "N/A"
                
                if is_bot_rabbit:
                    popup_msg = (
                        f"<b>{b_lbl}</b><br>"
                        f"Coordinates: Lat: {b_lat:.5f}, Lon: {b_lon:.5f}<br>"
                        f"Timestamp: {b_time}"
                    )
                    folium.Marker(location=[b_lat, b_lon], popup=popup_msg, icon=folium.Icon(color=track_color, icon='info-sign')).add_to(bot_fg)
                else:
                    popup_msg = (
                        f"<b>{b_lbl}</b><br>"
                        f"Coordinates: Lat: {b_lat:.5f}, Lon: {b_lon:.5f}<br>"
                        f"Timestamp: {b_time}<br>"
                        f"LOB Abs Degree: {latest_bot_lob_str}"
                    )
                    folium.CircleMarker(location=[b_lat, b_lon], radius=7, color=track_color, fill=True, popup=popup_msg).add_to(bot_fg)
                    
                    if b_lob is not None:
                        cone_l = 0.08
                        fov_h = 20.0
                        ang_l, ang_r = math.radians(b_lob - fov_h), math.radians(b_lob + fov_h)
                        folium.PolyLine([[b_lat, b_lon], [b_lat + (cone_l * math.cos(ang_l)), b_lon + (cone_l * math.sin(ang_l))]], color=track_color, weight=2).add_to(bot_fg)
                        folium.PolyLine([[b_lat, b_lon], [b_lat + (cone_l * math.cos(ang_r)), b_lon + (cone_l * math.sin(ang_r))]], color=track_color, weight=2).add_to(bot_fg)
                
                if not is_bot_rabbit:
                    folium.Marker(
                        location=[b_lat + 0.004, b_lon],
                        icon=folium.DivIcon(
                            html=f"""<div style="font-family: sans-serif; font-size: 11px; font-weight: bold; color: black; background-color: rgba(255,255,255,0.7); padding: 2px 4px; border-radius: 3px; border: 1px solid {track_color}; white-space: nowrap; margin-top: -12px;">{b_lbl}: {latest_bot_lob_str}</div>"""
                        )
                    ).add_to(bot_fg)
                
                bot_fg.add_to(my_map)
                active_legend_items.append((b_lbl, track_color))

        if my_map is None:
            my_map = folium.Map(location=[35.219, -116.648], zoom_start=12, prefer_canvas=True)

        folium.LayerControl().add_to(my_map)

        box_height = 40 + (len(active_legend_items) * 22)
        legend_rows_html = "".join([f'<i style="background:{c}; width:10px; height:10px; float:left; margin-right:5px; margin-top:4px;"></i> {n}<br>' for n, c in active_legend_items])
        legend_html = f'<div style="position: fixed; bottom: 50px; left: 50px; width: 160px; height: {box_height}px; background-color: white; border:2px solid grey; z-index:9999; font-size:13px; padding: 10px; font-family: sans-serif; box-shadow: 2px 2px 5px rgba(0,0,0,0.2);"><b>Legend ({selected_date})</b><br>{legend_rows_html}</div>'
        my_map.get_root().html.add_child(folium.Element(legend_html))
        
        remove_scrollbars_css = "<style>html, body { overflow: hidden !important; margin: 0 !important; padding: 0 !important; width: 100% !important; height: 100% !important; } ::-webkit-scrollbar { display: none !important; width: 0 !important; height: 0 !important; }</style>"
        my_map.get_root().html.add_child(folium.Element(remove_scrollbars_css))
        
        persistent_view_js = """
        <style>
            .folium-map { opacity: 0; }
        </style>
        <script>
            (function() {
                var hiddenLayers = JSON.parse(localStorage.getItem('dash_hidden_layers') || '[]');
                var savedCenter = localStorage.getItem('dash_map_center');
                var savedZoom = localStorage.getItem('dash_map_zoom');

                function applySavedState() {
                    var maps = Object.keys(window).filter(k => k.startsWith('map_'));
                    if (maps.length === 0) return false;

                    var mapObj = window[maps];
                    var mapContainer = mapObj.getContainer();

                    if (savedCenter && savedZoom) {
                        mapObj.setView(JSON.parse(savedCenter), parseInt(savedZoom), {animate: false});
                    }

                    var labels = document.querySelectorAll('.leaflet-control-layers-overlays label');
                    labels.forEach(function(label) {
                        var name = label.textContent.trim();
                        var checkbox = label.querySelector('input[type="checkbox"]');
                        if (checkbox && hiddenLayers.includes(name) && checkbox.checked) {
                            checkbox.click();
                        }
                    });

                    if (mapContainer) {
                        mapContainer.style.opacity = '1';
                    }

                    mapObj.on('moveend zoomend', function() {
                        localStorage.setItem('dash_map_center', JSON.stringify(mapObj.getCenter()));
                        localStorage.setItem('dash_map_zoom', mapObj.getZoom());
                    });
                    mapObj.on('overlayremove', function(e) {
                        var current = JSON.parse(localStorage.getItem('dash_hidden_layers') || '[]');
                        if (!current.includes(e.name)) {
                            current.push(e.name);
                            localStorage.setItem('dash_hidden_layers', JSON.stringify(current));
                        }
                    });
                    mapObj.on('overlayadd', function(e) {
                        var current = JSON.parse(localStorage.getItem('dash_hidden_layers') || '[]');
                        current = current.filter(function(item) { return item !== e.name; });
                        localStorage.setItem('dash_hidden_layers', JSON.stringify(current));
                    });

                    return true;
                }

                var observer = new MutationObserver(function() {
                    if (applySavedState()) {
                        observer.disconnect();
                    }
                });
                observer.observe(document.documentElement, { childList: true, subtree: true });

                document.addEventListener("DOMContentLoaded", function() {
                    if (applySavedState()) {
                        observer.disconnect();
                    } else {
                        var maps = Object.keys(window).filter(k => k.startsWith('map_'));
                        if (maps.length > 0) window[maps].getContainer().style.opacity = '1';
                    }
                });
            })();
        </script>
        """
        my_map.get_root().html.add_child(folium.Element(persistent_view_js))
        return my_map.get_root().render()

    except Exception as err:
        return f"⚠️ Dashboard Integration Matrix Exception Error: {str(err)}"


if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=8055)