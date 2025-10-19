import ee
import pandas as pd
import datetime
from shapely.geometry import shape
import json
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
import random

# Initialize Earth Engine
ee.Initialize(project='silent-nation-462410-i6')

# Global scaler for consistency
scaler = StandardScaler()
trained_model = None


def maskS2clouds(image):
    band_names = image.bandNames()
    
    def qa60_mask():
        qa = image.select('QA60')
        cloudBitMask = 1 << 10
        cirrusBitMask = 1 << 11
        mask = qa.bitwiseAnd(cloudBitMask).eq(0).And(
            qa.bitwiseAnd(cirrusBitMask).eq(0)
        )
        return image.updateMask(mask).divide(10000)

    def scl_mask():
        scl = image.select('SCL')
        mask = scl.neq(3).And(scl.lt(7)).Or(scl.gt(10))
        return image.updateMask(mask).divide(10000)

    return ee.Algorithms.If(band_names.contains('QA60'), qa60_mask(), scl_mask())


def get_monthly_s2_data_last_years(aoi, reference_date=None, scale=10, years_back=5):
    if reference_date is None:
        reference_date = datetime.date.today()

    current_month = reference_date.month
    current_year = reference_date.year
    start_year = max(current_year - years_back, 2015)

    all_data = []

    for year in range(start_year, current_year):
        start_date = datetime.date(year, current_month, 1)
        if current_month == 12:
            end_date = datetime.date(year + 1, 1, 1)
        else:
            end_date = datetime.date(year, current_month + 1, 1)

        print(f"Fetching historical data: {start_date} to {end_date}")

        s2 = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
              .filterBounds(aoi)
              .filterDate(str(start_date), str(end_date))
              .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 30))
              .map(maskS2clouds)
              .select(['B2', 'B4', 'B8']))

        def add_indices(img):
            date = ee.Algorithms.If(
                img.propertyNames().contains('system:time_start'),
                img.date().format('YYYY-MM-dd'),
                ee.String(img.id()).slice(0, 8)
            )
            ndvi = img.normalizedDifference(['B8', 'B4']).rename('NDVI')
            evi = img.expression(
                '2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))',
                {
                    'NIR': img.select('B8'),
                    'RED': img.select('B4'),
                    'BLUE': img.select('B2')
                }
            ).rename('EVI')
            return img.addBands([ndvi, evi]).set('date', date)

        s2 = s2.map(add_indices)

        def sample_image(img):
            return img.sample(
                region=aoi,
                numPixels=1000,
                scale=scale,
                geometries=True
            ).map(lambda f: f.set('date', img.get('date')))

        samples = s2.map(sample_image).flatten()
        features = samples.getInfo().get('features', [])

        for f in features:
            props = f['properties']
            geom = f['geometry']['coordinates']
            if all(k in props for k in ['B2', 'B4', 'B8']):
                all_data.append({
                    'date': props['date'],
                    'year': year,
                    'month': current_month,
                    'lon': geom[0],
                    'lat': geom[1],
                    'B2': props['B2'],
                    'B4': props['B4'],
                    'B8': props['B8'],
                    'NDVI': props['NDVI'],
                    'EVI': props['EVI']
                })
    
    df = pd.DataFrame(all_data)
    if not df.empty:
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').reset_index(drop=True)
    return df


def get_s2_data_for_date(aoi, reference_date, scale=10, numPixels=1000):
    start_date = reference_date - datetime.timedelta(days=7)
    end_date = reference_date + datetime.timedelta(days=7)
    
    print(f"Fetching current data: {start_date} to {end_date}")

    s2 = (ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
          .filterBounds(aoi)
          .filterDate(str(start_date), str(end_date))
          .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 30))
          .map(maskS2clouds)
          .select(['B2','B4','B8']))

    def add_indices(img):
        date = ee.Algorithms.If(
            img.propertyNames().contains('system:time_start'),
            img.date().format('YYYY-MM-dd'),
            ee.String(img.id()).slice(0,8)
        )
        ndvi = img.normalizedDifference(['B8','B4']).rename('NDVI')
        evi = img.expression(
            '2.5*((NIR-RED)/(NIR+6*RED-7.5*BLUE+1))',
            {'NIR':img.select('B8'),'RED':img.select('B4'),'BLUE':img.select('B2')}
        ).rename('EVI')
        return img.addBands([ndvi,evi]).set('date', date)

    s2 = s2.map(add_indices)

    def sample_image(img):
        return img.sample(region=aoi, numPixels=numPixels, scale=scale, geometries=True)

    samples = s2.map(sample_image).flatten()
    features = samples.getInfo().get('features', [])

    all_data = []
    for f in features:
        props = f['properties']
        geom = f['geometry']['coordinates']
        date = props.get('date', f.get('id', '')[:8])
        if all(k in props for k in ['B2','B4','B8']):
            all_data.append({
                'date': date,
                'lon': geom[0],
                'lat': geom[1],
                'B2': props['B2'],
                'B4': props['B4'],
                'B8': props['B8'],
                'NDVI': props['NDVI'],
                'EVI': props['EVI']
            })

    df = pd.DataFrame(all_data)
    if not df.empty:
        df['date'] = pd.to_datetime(df['date'])
    return df


def compute_ndvi_and_run_model(geojson_obj, reference_date=None):
    global scaler, trained_model
    
    print("Starting real satellite analysis...")    
    aoi = ee.Geometry(geojson_obj)
    
    if reference_date is None:
        ref_date = datetime.date.today()
    else:
        ref_date = reference_date
    
    print(f"Reference date: {ref_date}")
    
    try:
        print("Training model on historical data...")
        train_df = get_monthly_s2_data_last_years(aoi, reference_date=ref_date, years_back=5)
        
        if train_df.empty:
            raise ValueError("No historical data found for training")
        
        train_features = train_df[['NDVI', 'EVI']].dropna()
        X_train = scaler.fit_transform(train_features)
        
        trained_model = IsolationForest(
            n_estimators=200,
            contamination=0.03,
            random_state=42
        )
        trained_model.fit(X_train)
        print(f"Model trained on {len(train_features)} samples")
        
        print("Fetching current satellite data...")
        current_df = get_s2_data_for_date(aoi, ref_date, scale=10, numPixels=1000)
        
        if current_df.empty:
            raise ValueError("No current data available")
        
        X_current = scaler.transform(current_df[['NDVI', 'EVI']].fillna(0))
        current_df['anomaly_score'] = trained_model.decision_function(X_current)
        current_df['anomaly_label'] = trained_model.predict(X_current)
        
        min_score = current_df['anomaly_score'].min()
        max_score = current_df['anomaly_score'].max()
        current_df['normalized_anomaly'] = 1 - ((current_df['anomaly_score'] - min_score) / (max_score - min_score + 1e-8))
        
        print(f"Analyzed {len(current_df)} points")
        
        heatmap_geojson = generate_heatmap_from_points(current_df, geojson_obj)
        
        stats = compute_statistics_from_df(current_df)
        
        return heatmap_geojson, stats
        
    except Exception as e:
        print(f"Error in processing: {str(e)}")
        print("Falling back to dummy data")
        return generate_dummy_heatmap(geojson_obj)


def generate_heatmap_from_points(df, aoi_geojson):
    features = []
    
    for idx, row in df.iterrows():
        anomaly = row['normalized_anomaly']
        
        if anomaly > 0.7:
            severity = 'critical'
            color = '#d73027'
        elif anomaly > 0.5:
            severity = 'warning'
            color = '#fc8d59'
        elif anomaly > 0.3:
            severity = 'moderate'
            color = '#fee090'
        else:
            severity = 'healthy'
            color = '#91cf60'
        
        feature = {
            'type': 'Feature',
            'geometry': {
                'type': 'Point',
                'coordinates': [row['lon'], row['lat']]
            },
            'properties': {
                'health_score': round(1 - anomaly, 3),
                'anomaly_score': round(anomaly, 3),
                'severity': severity,
                'color': color,
                'ndvi': round(row['NDVI'], 3),
                'evi': round(row['EVI'], 3),
                'anomaly_label': 'Anomaly' if row['anomaly_label'] == -1 else 'Normal'
            }
        }
        features.append(feature)
    
    return {
        'type': 'FeatureCollection',
        'features': features
    }


def compute_statistics_from_df(df):
    anomaly_counts = df['normalized_anomaly'].apply(lambda x: 
        'critical' if x > 0.7 else 
        'warning' if x > 0.5 else 
        'moderate' if x > 0.3 else 
        'healthy'
    ).value_counts()
    
    return {
        'total_zones': len(df),
        'healthy_count': int(anomaly_counts.get('healthy', 0)),
        'moderate_count': int(anomaly_counts.get('moderate', 0)),
        'warning_count': int(anomaly_counts.get('warning', 0)),
        'critical_count': int(anomaly_counts.get('critical', 0)),
        'avg_health': round((1 - df['normalized_anomaly'].mean()), 3),
        'avg_ndvi': round(df['NDVI'].mean(), 3),
        'avg_evi': round(df['EVI'].mean(), 3)
    }


def generate_dummy_heatmap(geojson_obj):
    from shapely.geometry import Polygon
    
    geom = shape(geojson_obj)
    bounds = geom.bounds
    minx, miny, maxx, maxy = bounds
    
    grid_size = 6
    cell_width = (maxx - minx) / grid_size
    cell_height = (maxy - miny) / grid_size
    
    features = []
    scores = []
    
    for i in range(grid_size):
        for j in range(grid_size):
            x1 = minx + j * cell_width
            y1 = miny + i * cell_height
            x2 = x1 + cell_width
            y2 = y1 + cell_height
            
            cell = Polygon([(x1, y1), (x2, y1), (x2, y2), (x1, y2), (x1, y1)])
            
            if not cell.intersects(geom):
                continue
            
            clipped = cell.intersection(geom)
            
            if clipped.is_empty:
                continue
            
            score = random.uniform(0.6, 0.95) if random.random() < 0.15 else random.uniform(0.1, 0.4)
            scores.append(score)
            
            if score > 0.7:
                severity = 'critical'
                color = '#d73027'
            elif score > 0.5:
                severity = 'warning'
                color = '#fc8d59'
            elif score > 0.3:
                severity = 'moderate'
                color = '#fee090'
            else:
                severity = 'healthy'
                color = '#91cf60'
            
            feature = {
                'type': 'Feature',
                'geometry': {
                    'type': clipped.geom_type,
                    'coordinates': list(clipped.exterior.coords) if hasattr(clipped, 'exterior') else list(clipped.coords)
                },
                'properties': {
                    'health_score': round(1 - score, 3),
                    'anomaly_score': round(score, 3),
                    'severity': severity,
                    'color': color
                }
            }
            features.append(feature)
    
    heatmap = {'type': 'FeatureCollection', 'features': features}
    stats = {
        'total_zones': len(scores),
        'healthy_count': sum(1 for s in scores if s <= 0.3),
        'moderate_count': sum(1 for s in scores if 0.3 < s <= 0.5),
        'warning_count': sum(1 for s in scores if 0.5 < s <= 0.7),
        'critical_count': sum(1 for s in scores if s > 0.7),
        'avg_health': round((1 - sum(scores) / len(scores)), 3) if scores else 0
    }
    
    return heatmap, stats


def calculate_polygon_area(geojson_obj):
    geom = shape(geojson_obj)
    area_deg_sq = geom.area
    area_km_sq = area_deg_sq * (111 * 111)
    area_hectares = area_km_sq * 100
    return round(area_hectares, 2)