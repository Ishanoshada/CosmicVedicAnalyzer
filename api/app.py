from flask import Flask, request, render_template, redirect, url_for, abort, send_from_directory
from werkzeug.utils import secure_filename
import pandas as pd
try:
    from .astrology_analyzer import AstrologyAnalyzer
except:
    from astrology_analyzer import AstrologyAnalyzer
import io
import re
import os
from datetime import datetime
import numpy as np

app = Flask(__name__)

def extract_datetime_components(date_str):
    """Try to parse various date formats into components"""
    if not isinstance(date_str, str):
        return None
    
    # Handle negative years (BCE dates)
    negative_year = False
    if date_str.startswith('-'):
        negative_year = True
        date_str = date_str[1:]  # Remove the negative sign
    
    # Clean the date string
    date_str = date_str.strip()
    
    # If it's just a year
    if date_str.isdigit() and len(date_str) <= 4:
        year = int(date_str)
        if negative_year:
            year = -year
        return {
            'YEAR': year,
            'MONTH': 1,
            'DAY': 1,
            'HOUR': 12,
            'MINUTE': 0
        }
    
    try:
        # Try ISO format first
        dt = datetime.fromisoformat(date_str)
        return {
            'YEAR': dt.year if not negative_year else -dt.year,
            'MONTH': dt.month,
            'DAY': dt.day,
            'HOUR': dt.hour,
            'MINUTE': dt.minute
        }
    except (ValueError, AttributeError):
        pass
    
    # Try other common formats
    formats = [
        ('%Y-%m-%d %H:%M:%S', 1),
        ('%Y-%m-%d %H:%M', 1),
        ('%d-%m-%Y %H:%M:%S', 1),
        ('%d-%m-%Y %H:%M', 1),
        ('%m/%d/%Y %H:%M', 1),
        ('%d/%m/%Y %H:%M', 1),
        ('%d-%b-%Y %H:%M', 1),
        ('%d-%b-%Y %H:%M:%S', 1),
        ('%Y-%m-%d', 0),  # Date only
        ('%m/%d/%Y', 0),  # Date only
        ('%d/%m/%Y', 0),  # Date only
        ('%d-%m-%Y', 0),  # Date only
    ]
    
    for fmt, has_time in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            return {
                'YEAR': dt.year if not negative_year else -dt.year,
                'MONTH': dt.month,
                'DAY': dt.day,
                'HOUR': dt.hour if has_time else 12,
                'MINUTE': dt.minute if has_time else 0
            }
        except ValueError:
            continue
    
    # Custom format for DD-MM-YYYY HH:MM
    try:
        date_pattern = r'(\d{2})-(\d{2})-(\d{4})\s+(\d{1,2}):(\d{2})'
        match = re.match(date_pattern, date_str)
        if match:
            day, month, year, hour, minute = match.groups()
            year_val = int(year)
            if negative_year:
                year_val = -year_val
            return {
                'YEAR': year_val,
                'MONTH': int(month),
                'DAY': int(day),
                'HOUR': int(hour),
                'MINUTE': int(minute)
            }
    except:
        pass
    
    return None

def extract_coordinates(location_str):
    """Extract lat/long from various location formats"""
    if not isinstance(location_str, str):
        return None, None
    
    # Try decimal degrees format
    decimal_pattern = r'(-?\d+\.\d+)[, ]+(-?\d+\.\d+)'
    match = re.search(decimal_pattern, location_str)
    if match:
        return float(match.group(1)), float(match.group(2))
    
    # Try parenthesized coordinates format like (50.775000, 6.083330)
    parens_pattern = r'\((-?\d+\.\d+)[, ]+(-?\d+\.\d+)\)'
    match = re.search(parens_pattern, location_str)
    if match:
        return float(match.group(1)), float(match.group(2))
    
    # Try DMS format
    dms_pattern = r'(\d+)°(\d+)\'(\d+\.?\d*)"([NS]),?\s*(\d+)°(\d+)\'(\d+\.?\d*)"([EW])'
    match = re.search(dms_pattern, location_str)
    if match:
        lat_deg, lat_min, lat_sec, lat_dir = match.group(1, 2, 3, 4)
        lon_deg, lon_min, lon_sec, lon_dir = match.group(5, 6, 7, 8)
        
        lat = float(lat_deg) + float(lat_min)/60 + float(lat_sec)/3600
        if lat_dir.upper() == 'S':
            lat = -lat
            
        lon = float(lon_deg) + float(lon_min)/60 + float(lon_sec)/3600
        if lon_dir.upper() == 'W':
            lon = -lon
            
        return lat, lon
    
    return None, None

def identify_column_types(df):
    """Identify different types of columns in the dataframe"""
    column_types = {
        'date': [],
        'time': [],
        'datetime': [],
        'year': [],
        'magnitude': [],
        'latitude': [],
        'longitude': [],
        'location': [],
        'depth': [],
        'elevation': [],
        'vei': [],  # Volcanic Explosivity Index
        'mass': [],  # For meteorites
        'type': [],  # For volcano/meteorite type
        'name': [],  # For volcano/meteorite name
        'country': []  # For country
    }
    
    # Check each column name for keywords
    for col in df.columns:
        col_lower = str(col).lower()
        
        # Check for date/time columns
        if any(kw in col_lower for kw in ['date_time', 'datetime', 'geolocation']):
            column_types['datetime'].append(col)
        elif 'date' in col_lower:
            column_types['date'].append(col)
        elif 'time' in col_lower:
            column_types['time'].append(col)
        elif 'year' == col_lower:
            column_types['year'].append(col)
            
        # Check for magnitude columns
        if any(kw in col_lower for kw in ['magnitude', 'mag', ' m ']):
            column_types['magnitude'].append(col)
            
        # Check for VEI columns
        if 'vei' == col_lower:
            column_types['vei'].append(col)
            
        # Check for mass columns (meteorites)
        if 'mass' == col_lower:
            column_types['mass'].append(col)
            
        # Check for coordinate columns
        if any(kw == col_lower for kw in ['latitude', 'lat', 'reclat']):
            column_types['latitude'].append(col)
        if any(kw == col_lower for kw in ['longitude', 'long', 'lon', 'reclong']):
            column_types['longitude'].append(col)
            
        # Check for location columns
        if any(kw in col_lower for kw in ['location', 'place']):
            column_types['location'].append(col)
            
        # Check for depth columns
        if 'depth' in col_lower:
            column_types['depth'].append(col)
            
        # Check for elevation columns
        if 'elevation' in col_lower:
            column_types['elevation'].append(col)
            
        # Check for type columns
        if any(kw == col_lower for kw in ['type', 'recclass', 'nametype']):
            column_types['type'].append(col)
            
        # Check for name columns
        if any(kw == col_lower for kw in ['name']):
            column_types['name'].append(col)
            
        # Check for country columns
        if 'country' == col_lower:
            column_types['country'].append(col)
    
    # If we don't have explicit columns, try to identify by content
    if not column_types['magnitude'] and not column_types['vei']:
        for col in df.columns:
            # Try to identify magnitude columns (typically small numbers < 10)
            if df[col].dtype in [np.float64, np.int64, np.float32, np.int32]:
                try:
                    values = pd.to_numeric(df[col], errors='coerce')
                    if values.min() >= 0 and values.max() <= 10:
                        column_types['magnitude'].append(col)
                        break
                except:
                    continue
    
    return column_types

def extract_magnitude(df, column_types):
    """Try to extract magnitude from various column formats"""
    # First check for VEI (Volcanic Explosivity Index)
    if column_types['vei']:
        return pd.to_numeric(df[column_types['vei'][0]], errors='coerce')
    
    # Then check for regular magnitude columns
    if column_types['magnitude']:
        return pd.to_numeric(df[column_types['magnitude'][0]], errors='coerce')
    
    # Then check for mass (meteorites)
    if column_types['mass']:
        # For mass, we'll log-normalize it to a scale similar to magnitude
        mass_values = pd.to_numeric(df[column_types['mass'][0]], errors='coerce')
        # Avoid log(0) errors
        mass_values = mass_values.replace(0, np.nan)
        if not mass_values.isna().all():
            log_mass = np.log10(mass_values)
            # Scale to a range similar to earthquake magnitudes (0-10)
            min_log = log_mass.min()
            max_log = log_mass.max()
            if not np.isnan(min_log) and not np.isnan(max_log) and min_log != max_log:
                return ((log_mass - min_log) / (max_log - min_log)) * 10
    
    # If no explicit magnitude column, look for a column with values between 0 and 10
    for col in df.columns:
        if df[col].dtype in [np.float64, np.int64, np.float32, np.int32]:
            try:
                values = pd.to_numeric(df[col], errors='coerce')
                if values.min() >= 0 and values.max() <= 10 and values.mean() > 2:
                    return values
            except:
                continue
    
    # If all else fails, try to extract from the first column if it's a string
    # (sometimes descriptions contain magnitude like "M 6.5")
    if len(df.columns) > 0 and df[df.columns[0]].dtype == object:
        try:
            patterns = [r'M\s*(\d+\.\d+)', r'magnitude\s*(\d+\.\d+)', r'mag\s*(\d+\.\d+)']
            for pattern in patterns:
                mag_series = df[df.columns[0]].str.extract(pattern, expand=False)
                if not mag_series.isna().all():
                    return pd.to_numeric(mag_series, errors='coerce')
        except:
            pass
    
    # Default to 0 if no magnitude found
    return pd.Series([0.0] * len(df))

def normalize_csv(df):
    """Normalize different CSV formats to our required structure"""
    normalized = pd.DataFrame()
    
    # Identify column types
    column_types = identify_column_types(df)
    
    # Handle datetime columns
    datetime_cols = column_types['datetime']
    date_cols = column_types['date']
    time_cols = column_types['time']
    year_cols = column_types['year']
    
    # Process datetime information
    if datetime_cols:
        # If we have a datetime column, try to parse it
        datetime_col = datetime_cols[0]
        df[datetime_col] = df[datetime_col].astype(str)
        
        datetime_data = df[datetime_col].apply(extract_datetime_components)
        datetime_df = pd.DataFrame(datetime_data.tolist())
        
        for col in ['YEAR', 'MONTH', 'DAY', 'HOUR', 'MINUTE']:
            if col in datetime_df.columns:
                normalized[col] = datetime_df[col]
            else:
                normalized[col] = 1 if col in ['MONTH', 'DAY'] else (12 if col == 'HOUR' else 0)
    
    elif date_cols:
        # If we have separate date and time columns
        date_col = date_cols[0]
        df[date_col] = df[date_col].astype(str)
        
        # Parse date components
        if time_cols:
            # Combine date and time for parsing
            time_col = time_cols[0]
            df['temp_datetime'] = df[date_col] + ' ' + df[time_col].astype(str)
            datetime_data = df['temp_datetime'].apply(extract_datetime_components)
        else:
            datetime_data = df[date_col].apply(extract_datetime_components)
            
        datetime_df = pd.DataFrame(datetime_data.tolist())
        
        for col in ['YEAR', 'MONTH', 'DAY', 'HOUR', 'MINUTE']:
            if col in datetime_df.columns:
                normalized[col] = datetime_df[col]
            else:
                normalized[col] = 1 if col in ['MONTH', 'DAY'] else (12 if col == 'HOUR' else 0)
    
    elif year_cols:
        # If we only have year information (common for volcanic/geological data)
        year_col = year_cols[0]
        normalized['YEAR'] = pd.to_numeric(df[year_col], errors='coerce')
        
        # Default values for other time components
        normalized['MONTH'] = 1
        normalized['DAY'] = 1
        normalized['HOUR'] = 12
        normalized['MINUTE'] = 0
    
    else:
        # Try to find individual components
        for col in ['YEAR', 'MONTH', 'DAY', 'HOUR', 'MINUTE']:
            matching_cols = [c for c in df.columns if c.upper() == col]
            if matching_cols:
                normalized[col] = pd.to_numeric(df[matching_cols[0]], errors='coerce').fillna(
                    1 if col in ['MONTH', 'DAY'] else (12 if col == 'HOUR' else 0)
                )
            else:
                normalized[col] = 1 if col in ['MONTH', 'DAY'] else (12 if col == 'HOUR' else 0)
    
    # Handle location data
    lat_cols = column_types['latitude']
    lon_cols = column_types['longitude']
    loc_cols = column_types['location']
    geo_cols = [col for col in df.columns if 'geo' in str(col).lower() and 'location' in str(col).lower()]
    
    if lat_cols and lon_cols:
        # If we have explicit latitude and longitude columns
        normalized['LATITUDE'] = pd.to_numeric(df[lat_cols[0]], errors='coerce')
        normalized['LONGITUDE'] = pd.to_numeric(df[lon_cols[0]], errors='coerce')
    elif geo_cols:
        # Try to extract coordinates from GeoLocation string
        geo_col = geo_cols[0]
        df[geo_col] = df[geo_col].astype(str)
        
        # Apply function to extract coordinates from location string
        coords = df[geo_col].apply(lambda x: pd.Series(extract_coordinates(x)))
        normalized['LATITUDE'] = coords[0]
        normalized['LONGITUDE'] = coords[1]
    elif loc_cols:
        # Try to extract coordinates from location string
        loc_col = loc_cols[0]
        df[loc_col] = df[loc_col].astype(str)
        
        # Apply function to extract coordinates from location string
        coords = df[loc_col].apply(lambda x: pd.Series(extract_coordinates(x)))
        normalized['LATITUDE'] = coords[0]
        normalized['LONGITUDE'] = coords[1]
    else:
        # Check if we have columns that might be latitude/longitude
        for col in df.columns:
            col_str = str(col).lower()
            # Look for explicit latitude/longitude columns
            if 'latitude' in col_str or 'lat' == col_str or 'reclat' == col_str:
                normalized['LATITUDE'] = pd.to_numeric(df[col], errors='coerce')
            elif 'longitude' in col_str or 'lon' == col_str or 'long' == col_str or 'reclong' == col_str:
                normalized['LONGITUDE'] = pd.to_numeric(df[col], errors='coerce')
    
    # If we still don't have coordinates, default to 0,0
    if 'LATITUDE' not in normalized.columns:
        normalized['LATITUDE'] = 0.0
    if 'LONGITUDE' not in normalized.columns:
        normalized['LONGITUDE'] = 0.0
    
    # Extract magnitude
    normalized['MAGNITUDE'] = extract_magnitude(df, column_types)
    
    # Extract depth/elevation if available
    depth_cols = column_types['depth']
    elev_cols = column_types['elevation']
    
    if depth_cols:
        normalized['DEPTH'] = pd.to_numeric(df[depth_cols[0]], errors='coerce')
    elif elev_cols:
        # For volcanic data, elevation can be useful (convert to depth as negative elevation)
        normalized['DEPTH'] = -pd.to_numeric(df[elev_cols[0]], errors='coerce')
    else:
        # Try to find depth in any numeric column
        depth_found = False
        for col in df.columns:
            if df[col].dtype in [np.float64, np.int64, np.float32, np.int32]:
                col_str = str(col).lower()
                if 'depth' in col_str:
                    normalized['DEPTH'] = pd.to_numeric(df[col], errors='coerce')
                    depth_found = True
                    break
                elif 'elevation' in col_str:
                    normalized['DEPTH'] = -pd.to_numeric(df[col], errors='coerce')  # Negative elevation
                    depth_found = True
                    break
        
        # Default depth if not found
        if not depth_found:
            normalized['DEPTH'] = 0.0
    
    # Add additional useful information if available
    
    # Add name if available
    if column_types['name']:
        normalized['NAME'] = df[column_types['name'][0]]
    
    # Add type if available
    if column_types['type']:
        normalized['TYPE'] = df[column_types['type'][0]]
    
    # Add country if available
    if column_types['country']:
        normalized['COUNTRY'] = df[column_types['country'][0]]
    
    # Add location description if available
    if loc_cols:
        normalized['LOCATION'] = df[loc_cols[0]]
    
    # Drop rows with null values in critical columns
    normalized = normalized.dropna(subset=['YEAR'])
    
    # Fill missing coordinates with defaults
    normalized['LATITUDE'].fillna(0.0, inplace=True)
    normalized['LONGITUDE'].fillna(0.0, inplace=True)
    
    return normalized

def detect_format(df):
    """Detect the format of the uploaded CSV"""
    format_info = {
        'type': 'unknown',
        'columns': df.columns.tolist(),
        'example_row': df.iloc[0].to_dict() if len(df) > 0 else {}
    }
    
    # Check for earthquake data format
    earthquake_indicators = ['magnitude', 'mag', 'depth', 'tsunami', 'mmi', 'cdi', 'sig']
    earthquake_score = sum(1 for col in df.columns if any(ind in str(col).lower() for ind in earthquake_indicators))
    
    # Check for volcano data format
    volcano_indicators = ['volcano', 'vei', 'eruption', 'lava', 'caldera', 'stratovolcano']
    volcano_score = sum(1 for col in df.columns if any(ind in str(col).lower() for ind in volcano_indicators))
    
    # Check for meteorite data format
    meteorite_indicators = ['meteorite', 'fell', 'recclass', 'nametype', 'mass']
    meteorite_score = sum(1 for col in df.columns if any(ind in str(col).lower() for ind in meteorite_indicators))
    
    # Check sample values for additional clues
    sample_values = []
    for col in df.columns:
        try:
            if len(df) > 0 and df[col].dtype == object:
                sample_values.extend(str(val).lower() for val in df[col].head())
        except:
            continue
    
    # Look for keywords in sample values
    for value in sample_values:
        if any(ind in value for ind in volcano_indicators):
            volcano_score += 1
        if any(ind in value for ind in meteorite_indicators):
            meteorite_score += 1
    
    # Determine the dataset type based on scores
    if earthquake_score >= 2:
        format_info['type'] = 'earthquake'
    elif volcano_score >= 2:
        format_info['type'] = 'volcano'
    elif meteorite_score >= 2:
        format_info['type'] = 'meteorite'
    
    return format_info

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        if 'file' not in request.files:
            return render_template('index.html', error='No file uploaded')
        
        file = request.files['file']
        if file.filename == '':
            return render_template('index.html', error='No file selected')
        
        if file:
            try:
                # Read file directly without saving
                file_content = file.read().decode('utf-8')
                file_io = io.StringIO(file_content)
                
                # Try multiple CSV parsers with different delimiters
                tried_parsers = []
                df = None
                
                for delimiter in [',', ';', '\t', '|']:
                    try:
                        file_io.seek(0)  # Reset file pointer for next attempt
                        df = pd.read_csv(file_io, sep=delimiter)
                        if len(df.columns) > 1:  # Successfully parsed multiple columns
                            break
                        tried_parsers.append(f"Delimiter '{delimiter}': {len(df.columns)} columns")
                    except Exception as e:
                        tried_parsers.append(f"Delimiter '{delimiter}': {str(e)}")
                
                # If pandas couldn't parse it, try manual parsing
                if df is None or len(df.columns) <= 1 and ' ' in file_content:
                    # Try to split by whitespace and create columns
                    lines = file_content.strip().split('\n')
                    if len(lines) > 1:
                        # Use first line as header if it doesn't contain numbers
                        if not any(c.isdigit() for c in lines[0]):
                            header = lines[0].split()
                            data = [line.split() for line in lines[1:]]
                        else:
                            # Generate column names
                            max_cols = max(len(line.split()) for line in lines)
                            header = [f'Column{i+1}' for i in range(max_cols)]
                            data = [line.split() for line in lines]
                        
                        # Create DataFrame
                        df = pd.DataFrame(data, columns=header[:len(data[0])] if data else header)
                
                if df is None or len(df) == 0:
                    return render_template('index.html', error='Could not parse the file with any known format')
                
                # Clean the data - remove completely empty rows and columns
                df = df.dropna(how='all').dropna(axis=1, how='all')
                
                # Detect format
                format_info = detect_format(df)
                
                # Normalize the dataframe
                normalized_df = normalize_csv(df)
                
                if len(normalized_df) == 0:
                    return render_template('index.html', error='No valid data found in the file')
                
                # Process with analyzer
                analyzer = AstrologyAnalyzer(df=normalized_df)
                results = analyzer.analyze_events()
                
                return render_template('index.html', results=results, format_info=format_info)
                
            except Exception as e:
                return render_template('index.html', error=f'Error processing file: {str(e)}')
    
    return render_template('index.html')

DATASETS_DIR = os.path.join(app.static_folder, './')

# Route to serve sample dataset files
@app.route('/download/<filename>')
def download_file(filename):
    # Define allowed files to prevent unauthorized access
    allowed_files = [
        'earthquake_1995-2023.csv',
        'tsunami_dataset.csv',
        'volcano_eruptions.csv',
        'meteorite_landings.csv'
    ]
    
    # Check if the requested file is allowed
    if filename not in allowed_files:
        abort(404)  # Return 404 if file is not in the allowed list
    
    # Check if the file exists
    file_path = os.path.join(DATASETS_DIR, filename)
    if not os.path.isfile(file_path):
        abort(404)  # Return 404 if file doesn't exist
    
    # Serve the file
    return send_from_directory(DATASETS_DIR, filename, as_attachment=True)


if __name__ == '__main__':
    app.run(debug=True,host='0.0.0.0',port=8989)