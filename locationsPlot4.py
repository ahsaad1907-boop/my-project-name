import os
import glob
import re
import math
import pandas as pd
import folium
from dash import Dash, dcc, html, Input, Output, State

USER_HOME = os.path.expanduser("~")

DATA_ROOT = os.path.join(USER_HOME, "Downloads", "PCC6_DATA")

DATE_KEYS = ["15JUL", "16JUL", "17JUL", "18JUL", "21JUL", "23JUL", "24JUL"]
DATES_CONFIG = {
    date: os.path.join(DATA_ROOT, date) for date in DATE_KEYS
}


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
        df[lat_col] = pd.to_numeric(df[lat_col], errors="coerce")
        df[lon_col] = pd.to_numeric(df[lon_col], errors="coerce")
        df.dropna(subset=[lat_col, lon_col], inplace=True)
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
        excluded = False
        if exclude_keywords:
            excluded = (
                any(e.lower() in fn_lower for e in exclude_keywords) or 
                any(e.lower() in fp_lower for e in exclude_keywords)
            )
        if matches and not excluded:
            matched_paths.append(fp)
            
    return matched_paths


def extract_time_label(file_path, default_step_num):
    filename = os.path.basename(file_path)
    match_t = re.search(r'T(\d{2})(\d{2})\d{2}', filename)
    if match_t:
        return f"{match_t.group(1)}:{match_t.group(2)}"
    match_alt = re.search(r'_(\d{2})(\d{2})\d{2}', filename)
    if match_alt:
        return f"{match_alt.group(1)}:{match_alt.group(2)}"
    return f"Step {default_step_num}"


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
    
    total_found = len(r1_rabbit_paths) + len(r2_rabbit_paths) + len(v1_paths) + len(v2_paths) + len(v3_paths)
    print(f"Successfully cached {total_found} tracking tracks.")
    
    GLOBAL_DATA_CACHE[date_key] = {
        "r1_rabbit": [load_clean_file(p) for p in r1_rabbit_paths],
        "r2_rabbit": [load_clean_file(p) for p in r2_rabbit_paths],
        "v1_sensor": [load_clean_file(p) for p in v1_paths],
        "v2_sensor": [load_clean_file(p) for p in v2_paths],
        "v3_sensor": [load_clean_file(p) for p in v3_paths],
        "v1_paths_raw": v1_paths,
        "v2_paths_raw": v2_paths,
        "v3_paths_raw": v3_paths,
    }

print("Cache verification ready. Initializing web layout server...")


def lookup_timeline_scale(selected_date):
    day_cache = GLOBAL_DATA_CACHE[selected_date]
    ref_paths = day_cache["v1_paths_raw"]
    if not ref_paths:
        ref_paths = day_cache["v2_paths_raw"] or day_cache["v3_paths_raw"]
    if not ref_paths:
        return 1, {1: "Step 1"}
    max_steps = len(ref_paths)
    marks = {i + 1: extract_time_label(ref_paths[i], i + 1) for i in range(max_steps)}
    return max_steps, marks


app = Dash(__name__)
app.layout = html.Div([
    html.H1("Sensor Tracking Dashboard", style={'textAlign': 'center', 'fontFamily': 'sans-serif', 'margin': '10px 0'}),
    dcc.Tabs(
        id="date-tabs", value="15JUL", children=[dcc.Tab(label=date, value=date) for date in DATES_CONFIG.keys()],
        style={'fontFamily': 'sans-serif'}
    ),
    html.Div([
        html.Label("Adjust Chronological Time-Step Progression:", style={'fontWeight': 'bold', 'fontFamily': 'sans-serif'}),
        dcc.Slider(
            id='time-slider', min=1, max=5, step=1, value=1, marks={i: f'Step {i}' for i in range(1, 6)}
        )
    ], style={'width': '90%', 'margin': 'auto', 'padding': '15px 0 10px 0'}),
    html.Div([
        html.Iframe(id='folium-map', width='100%', height='100%', style={'border': 'none'})
    ], style={'flex': '1', 'width': '100%', 'position': 'relative', 'overflow': 'hidden'})
], style={
    'display': 'flex', 'flexDirection': 'column', 'height': '100vh', 'width': '100vw', 'margin': '0', 'padding': '0', 'overflow': 'hidden'
})


@app.callback(
    [Output('time-slider', 'max'), Output('time-slider', 'marks'), Output('time-slider', 'value')],
    Input('date-tabs', 'value'),
    State('time-slider', 'value')
)
def adjust_slider_scale_to_folder(selected_date, current_slider_val):
    max_steps, marks = lookup_timeline_scale(selected_date)
    new_val = min(current_slider_val, max_steps)
    return max_steps, marks, new_val

@app.callback(
    Output('folium-map', 'srcDoc'),
    Input('date-tabs', 'value'),
    Input('time-slider', 'value')
)
def update_map(selected_date, max_step):
    try:
        my_map = None
        total_day_steps, _ = lookup_timeline_scale(selected_date)
        use_sensors = selected_date in ["18JUL", "21JUL", "23JUL", "24JUL"]
        day_cache = GLOBAL_DATA_CACHE[selected_date]
        
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
            
            if len(parsed_list) > 1:
                limit = min(max_step, len(parsed_list))
                for idx in range(limit):
                    df, lt, ln, lb = parsed_list[idx]
                    if not df.empty:
                        combined_points.extend(df[[lt, ln]].values.tolist())
                        if lb and not df[lb].dropna().empty:
                            raw_lob_degrees = float(df[lb].iloc[-1])
                            latest_lob_val = f"{raw_lob_degrees}°"
            else:
                df, lt, ln, lb = parsed_list[0]
                if not df.empty:
                    total_rows = len(df)
                    rows_to_take = int((max_step / total_day_steps) * total_rows)
                    rows_to_take = max(1, min(rows_to_take, total_rows))
                    sliced_df = df.iloc[:rows_to_take]
                    combined_points = sliced_df[[lt, ln]].values.tolist()
                    if lb and not sliced_df[lb].dropna().empty:
                        raw_lob_degrees = float(sliced_df[lb].iloc[-1])
                        latest_lob_val = f"{raw_lob_degrees}°"
                        
            if combined_points:
                if my_map is None:
                    my_map = folium.Map(location=combined_points[0], zoom_start=12)
                folium.PolyLine(
                    combined_points, color=color, weight=3, opacity=0.8
                ).add_to(feature_group)
                
                popup_msg = f"<b>{layer_name}</b><br>LOB Abs Degree: {latest_lob_val}"
                current_head = combined_points[-1]
                if is_rabbit:
                    folium.Marker(
                        location=current_head, popup=popup_msg, icon=folium.Icon(color=color)
                    ).add_to(feature_group)
                else:
                    folium.CircleMarker(
                        location=current_head, radius=7, color=color, fill=True, popup=popup_msg
                    ).add_to(feature_group)
                    
                if raw_lob_degrees is not None:
                    cone_length = 0.08
                    fov_half_angle = 25.0
                    angle_left = math.radians(raw_lob_degrees - fov_half_angle)
                    angle_right = math.radians(raw_lob_degrees + fov_half_angle)
                    left_lat = current_head[0] + (cone_length * math.cos(angle_left))
                    left_lon = current_head[1] + (cone_length * math.sin(angle_left))
                    right_lat = current_head[0] + (cone_length * math.cos(angle_right))
                    right_lon = current_head[1] + (cone_length * math.sin(angle_right))
                    
                    folium.PolyLine(
                        [current_head, [left_lat, left_lon]], color=color, weight=2, opacity=0.6, dash_array='5,5'
                    ).add_to(feature_group)
                    folium.PolyLine(
                        [current_head, [right_lat, right_lon]], color=color, weight=2, opacity=0.6, dash_array='5,5'
                    ).add_to(feature_group)
                    
                if latest_lob_val != "N/A":
                    folium.Marker(
                        location=[current_head[0] + 0.001, current_head[1]],
                        icon=folium.DivIcon(
                            html=f"""<div style="font-family: sans-serif; font-size: 11px; font-weight: bold; color: black; background-color: rgba(255,255,255,0.7); padding: 2px 4px; border-radius: 3px; border: 1px solid {color}; white-space: nowrap;"> {layer_name}: {latest_lob_val} </div>"""
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
            f'<i style="background:{color}; width:10px; height:10px; float:left; margin-right:5px; margin-top:4px;"></i> {name}<br>'
            for name, color in active_legend_items
        ])
        legend_html = (
            f'<div style="position: fixed; bottom: 50px; left: 50px; width: 160px; height: {box_height}px; background-color: white; border:2px solid grey; z-index:9999; font-size:13px; padding: 10px; font-family: sans-serif; box-shadow: 2px 2px 5px rgba(0,0,0,0.2);">'
            f'<b>Legend ({selected_date})</b><br>{legend_rows_html}</div>'
        )
        my_map.get_root().html.add_child(folium.Element(legend_html))
        return my_map.get_root().render()
    except Exception as err:
        return f"<h4>Dashboard Integration Matrix Exception Error: {str(err)}</h4>"


if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=8055)