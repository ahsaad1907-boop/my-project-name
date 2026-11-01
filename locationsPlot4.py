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

print("Cache verification ready. Initializing web layout server...")


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


app = Dash(__name__)
app.layout = html.Div([
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
        html.Label(
            "Adjust Chronological Time (Minute Window Selection):", 
            style={'fontWeight': 'bold', 'fontFamily': 'sans-serif'}
        ),
        dcc.RangeSlider(
            id='time-slider', min=0, max=100, step=1, value=[0, 100],
            marks={0: '00:00'}
        ),
        dcc.Interval(
            id="play-interval", interval=300, n_intervals=0, disabled=True
        ),
        html.Div(
            style={'display': 'none'},
            children=html.Iframe(
                srcDoc="""
                <style>
                    body { display: none; }
                    parent .rc-slider-mark-text { font-size: 8px !important; }
                </style>
                """
            )
        )
    ], id="controls-container", style={
        'width': '90%', 'margin': 'auto', 'padding': '15px 0 10px 0',
        'display': 'flex', 'alignItems': 'center'
    }),
    
    html.Div([
        html.Iframe(
            id='folium-map', width='100%', height='100%', style={'border': 'none'}
        )
    ], style={
        'flex': '1', 'width': '100%', 'position': 'relative', 'overflow': 'hidden'
    })
], id="main-layout", style={
    'display': 'flex', 'flexDirection': 'column', 'height': '100vh', 'width': '100vw', 
    'margin': '0', 'padding': '0', 'overflow': 'hidden'
})


@app.callback(
    [Output('play-button', 'children'),
     Output('play-interval', 'disabled')],
    [Input('play-button', 'n_clicks'),
     Input('time-slider', 'value')],
    [State('time-slider', 'max')]
)
def toggle_playback(n_clicks, current_range, max_val):
    if n_clicks == 0:
        return "▶ Play", True
    if current_range[0] >= current_range[1]:
        return "▶ Play", True
    if n_clicks % 2 == 1:
        return "⏸ Pause", False
    else:
        return "▶ Play", True


@app.callback(
    [Output('time-slider', 'max'), 
     Output('time-slider', 'marks'), 
     Output('time-slider', 'value')],
    [Input('date-tabs', 'value'),
     Input('play-interval', 'n_intervals')],
    [State('time-slider', 'value')]
)
def update_slider_mechanics(selected_date, n_intervals, current_range):
    ctx = callback_context
    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0] if ctx.triggered else None
    
    total_range, marks = lookup_timeline_scale(selected_date)
    
    if trigger_id == 'date-tabs' or trigger_id is None:
        return total_range, marks, [0, total_range]
        
    if trigger_id == 'play-interval':
        low_handle = int(current_range[0]) + 1
        high_handle = int(current_range[1])
        
        if low_handle >= high_handle:
            low_handle = high_handle
            
        return total_range, marks, [low_handle, high_handle]
        
    return total_range, marks, current_range


@app.callback(
    Output('folium-map', 'srcDoc'),
    Input('date-tabs', 'value'),
    Input('time-slider', 'value')
)
def update_map(selected_date, slider_range_window):
    try:
        my_map = None
        day_cache = GLOBAL_DATA_CACHE[selected_date]
        
        start_minute_offset = day_cache["min_minute"]
        
        min_cutoff = start_minute_offset + int(slider_range_window[0])
        max_cutoff = start_minute_offset + int(slider_range_window[1])
        
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
                
            feature_group = folium.FeatureGroup(name=layer_name)
            combined_points = []
            latest_lob_val = "N/A"
            raw_lob_degrees = None
            
            for item in parsed_list:
                df, lt, ln, lb = item
                if df.empty:
                    continue
                    
                dt_col = 'normalized_minutes'
                sliced_df = df[(df[dt_col] >= min_cutoff) & (df[dt_col] <= max_cutoff)]
                if not sliced_df.empty:
                    combined_points.extend(
                        sliced_df[[lt, ln]].values.tolist()
                    )
                    if lb and not sliced_df[lb].dropna().empty:
                        raw_lob_degrees = float(sliced_df[lb].iloc[0])
                        latest_lob_val = f"{raw_lob_degrees}°"

            if combined_points:
                if my_map is None:
                    my_map = folium.Map(location=combined_points[0], zoom_start=12)
                
                folium.PolyLine(
                    combined_points, color=color, weight=3, opacity=0.8
                ).add_to(feature_group)
                
                popup_msg = f"<b>{layer_name}</b><br>LOB Abs Degree: {latest_lob_val}"
                trailing_head = combined_points[0]
                
                if is_rabbit:
                    folium.Marker(
                        location=trailing_head, popup=popup_msg, icon=folium.Icon(color=color)
                    ).add_to(feature_group)
                else:
                    folium.CircleMarker(
                        location=trailing_head, radius=7, color=color, fill=True, popup=popup_msg
                    ).add_to(feature_group)
                    
                    if raw_lob_degrees is not None:
                        cone_length = 0.08  
                        fov_half_angle = 25.0  
                        
                        angle_left = math.radians(raw_lob_degrees - fov_half_angle)
                        angle_right = math.radians(raw_lob_degrees + fov_half_angle)
                        
                        left_lat = trailing_head[0] + (cone_length * math.cos(angle_left))
                        left_lon = trailing_head[1] + (cone_length * math.sin(angle_left))
                        
                        right_lat = trailing_head[0] + (cone_length * math.cos(angle_right))
                        right_lon = trailing_head[1] + (cone_length * math.sin(angle_right))
                        
                        folium.PolyLine(
                            [trailing_head, [left_lat, left_lon]],
                            color=color, weight=2, opacity=0.6, dash_array='5,5'
                        ).add_to(feature_group)
                        
                        folium.PolyLine(
                            [trailing_head, [right_lat, right_lon]],
                            color=color, weight=2, opacity=0.6, dash_array='5,5'
                        ).add_to(feature_group)
                    
                    if latest_lob_val != "N/A":
                        folium.Marker(
                            location=[trailing_head[0] + 0.001, trailing_head[1]],
                            icon=folium.DivIcon(
                                html=f"""<div style="font-family: sans-serif; 
                                             font-size: 11px; font-weight: bold; 
                                             color: black; background-color: rgba(255,255,255,0.7);
                                             padding: 2px 4px; border-radius: 3px;
                                             border: 1px solid {color}; white-space: nowrap;">
                                             {layer_name}: {latest_lob_val}
                                         </div>"""
                            )
                        ).add_to(feature_group)
                
                active_legend_items.append((layer_name, color))
            
            if my_map is not None and combined_points:
                feature_group.add_to(my_map)

        if my_map is None:
            my_map = folium.Map(location=[35.219, -116.648], zoom_start=12)

        folium.LayerControl().add_to(my_map)

        box_height = 40 + (len(active_legend_items) * 22)
        legend_rows_html = "".join([
            f'<i style="background:{color}; width:10px; height:10px; '
            f'float:left; margin-right:5px; margin-top:4px;"></i> {name}<br>'
            for name, color in active_legend_items
        ])

        legend_html = (
            f'<div style="position: fixed; bottom: 50px; left: 50px; '
            f'width: 160px; height: {box_height}px; background-color: white; '
            f'border:2px solid grey; z-index:9999; font-size:13px; '
            f'padding: 10px; font-family: sans-serif; '
            f'box-shadow: 2px 2px 5px rgba(0,0,0,0.2);">'
            f'<b>Legend ({selected_date})</b><br>'
            f'{legend_rows_html}'
            f'</div>'
        )
        my_map.get_root().html.add_child(folium.Element(legend_html))
        
        return my_map.get_root().render()

    except Exception as err:
        return f"<h4>⚠️ Dashboard Integration Matrix Exception Error: {str(err)}</h4>"


if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=8055)