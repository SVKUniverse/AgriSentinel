from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime
import json

from models import db, User, LandParcel, Alert
from processing import compute_ndvi_and_run_model, calculate_polygon_area

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///agrisentinel.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)


# Authentication decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


# Helper to get current user
def get_current_user():
    if 'user_id' in session:
        return User.query.get(session['user_id'])
    return None


# Routes
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')


@app.route('/dashboard')
@login_required
def dashboard():
    user = get_current_user()
    parcels = LandParcel.query.filter_by(user_id=user.id).all()
    alerts = Alert.query.join(LandParcel).filter(LandParcel.user_id == user.id).order_by(Alert.created_at.desc()).limit(5).all()
    return render_template('index.html', user=user, parcels=parcels, alerts=alerts)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        
        # Validation
        if not username or not email or not password:
            flash('All fields are required.', 'danger')
            return render_template('register.html')
        
        # Check if user exists
        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger')
            return render_template('register.html')
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'danger')
            return render_template('register.html')
        
        # Create user
        user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password)
        )
        db.session.add(user)
        db.session.commit()
        
        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            session['username'] = user.username
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password.', 'danger')
    
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))


@app.route('/lands')
@login_required
def lands():
    user = get_current_user()
    parcels = LandParcel.query.filter_by(user_id=user.id).order_by(LandParcel.created_at.desc()).all()
    return render_template('lands.html', parcels=parcels)


@app.route('/lands/<int:land_id>')
@login_required
def land_detail(land_id):
    user = get_current_user()
    parcel = LandParcel.query.get_or_404(land_id)
    
    # Security: ensure user owns this parcel
    if parcel.user_id != user.id:
        flash('You do not have permission to view this plot.', 'danger')
        return redirect(url_for('lands'))
    
    # Parse GeoJSON for display
    geojson_data = json.loads(parcel.geojson)
    
    # Get alerts for this parcel
    alerts = Alert.query.filter_by(land_id=land_id).order_by(Alert.created_at.desc()).limit(10).all()
    
    return render_template('land_detail.html', parcel=parcel, geojson_data=geojson_data, alerts=alerts, datetime=datetime)


# REST API Endpoints
@app.route('/api/lands', methods=['GET', 'POST'])
@login_required
def api_lands():
    """
    GET: Return all parcels for current user as JSON
    POST: Create new land parcel
    """
    user = get_current_user()
    
    if request.method == 'GET':
        parcels = LandParcel.query.filter_by(user_id=user.id).all()
        return jsonify([{
            'id': p.id,
            'name': p.name,
            'description': p.description,
            'geojson': json.loads(p.geojson),
            'created_at': p.created_at.isoformat(),
            'last_computed_at': p.last_computed_at.isoformat() if p.last_computed_at else None
        } for p in parcels])
    
    elif request.method == 'POST':
        data = request.get_json()
        
        # Validation
        if not data.get('name'):
            return jsonify({'error': 'Name is required'}), 400
        
        if not data.get('geojson'):
            return jsonify({'error': 'GeoJSON is required'}), 400
        
        # Validate GeoJSON structure
        geojson_obj = data['geojson']
        if geojson_obj.get('type') not in ['Polygon', 'MultiPolygon']:
            return jsonify({'error': 'GeoJSON must be Polygon or MultiPolygon'}), 400
        
        # Create parcel
        parcel = LandParcel(
            user_id=user.id,
            name=data['name'],
            description=data.get('description', ''),
            geojson=json.dumps(geojson_obj)
        )
        db.session.add(parcel)
        db.session.commit()
        
        return jsonify({
            'id': parcel.id,
            'name': parcel.name,
            'description': parcel.description,
            'geojson': json.loads(parcel.geojson),
            'created_at': parcel.created_at.isoformat()
        }), 201


@app.route('/api/lands/<int:land_id>', methods=['GET', 'PUT', 'DELETE'])
@login_required
def api_land_detail(land_id):
    """
    GET: Return single parcel as JSON
    PUT: Update parcel
    DELETE: Delete parcel
    """
    user = get_current_user()
    parcel = LandParcel.query.get_or_404(land_id)
    
    # Security check
    if parcel.user_id != user.id:
        return jsonify({'error': 'Unauthorized'}), 403
    
    if request.method == 'GET':
        return jsonify({
            'id': parcel.id,
            'name': parcel.name,
            'description': parcel.description,
            'geojson': json.loads(parcel.geojson),
            'created_at': parcel.created_at.isoformat(),
            'last_computed_at': parcel.last_computed_at.isoformat() if parcel.last_computed_at else None
        })
    
    elif request.method == 'PUT':
        data = request.get_json()
        if 'name' in data:
            parcel.name = data['name']
        if 'description' in data:
            parcel.description = data['description']
        if 'geojson' in data:
            # Validate GeoJSON
            if data['geojson'].get('type') not in ['Polygon', 'MultiPolygon']:
                return jsonify({'error': 'GeoJSON must be Polygon or MultiPolygon'}), 400
            parcel.geojson = json.dumps(data['geojson'])
        
        db.session.commit()
        return jsonify({'message': 'Parcel updated successfully'})
    
    elif request.method == 'DELETE':
        # Delete associated alerts first
        Alert.query.filter_by(land_id=land_id).delete()
        db.session.delete(parcel)
        db.session.commit()
        return jsonify({'message': 'Plot deleted successfully'})


@app.route('/api/lands/<int:land_id>/compute', methods=['POST'])
@login_required
def api_compute_heatmap(land_id):
    user = get_current_user()
    parcel = LandParcel.query.get_or_404(land_id)
    
    # Security check
    if parcel.user_id != user.id:
        return jsonify({'error': 'Unauthorized'}), 403
    
    # Parse GeoJSON
    geojson_obj = json.loads(parcel.geojson)
    
    # Get reference date from request body (optional)
    data = request.get_json() or {}
    reference_date_str = data.get('reference_date')
    
    reference_date = None
    if reference_date_str:
        try:
            reference_date = datetime.strptime(reference_date_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400
    
    # Call processing function with reference date
    heatmap_geojson, stats = compute_ndvi_and_run_model(geojson_obj, reference_date)
    
    # Update last computed timestamp
    parcel.last_computed_at = datetime.utcnow()
    db.session.commit()
    
    # Create alerts for critical areas (if any)
    critical_count = stats.get('critical_count', 0)
    if critical_count > 0:
        alert = Alert(
            land_id=land_id,
            severity='critical',
            message=f'Detected {critical_count} critical health zones in {parcel.name}'
        )
        db.session.add(alert)
        db.session.commit()
    
    return jsonify({
        'heatmap': heatmap_geojson,
        'stats': stats,
        'computed_at': parcel.last_computed_at.isoformat(),
        'reference_date': reference_date_str if reference_date_str else datetime.now().strftime('%Y-%m-%d')
    })


@app.route('/api/lands/<int:land_id>/area', methods=['GET'])
@login_required
def api_land_area(land_id):
    user = get_current_user()
    parcel = LandParcel.query.get_or_404(land_id)
    
    if parcel.user_id != user.id:
        return jsonify({'error': 'Unauthorized'}), 403
    
    geojson_obj = json.loads(parcel.geojson)
    area_hectares = calculate_polygon_area(geojson_obj)
    
    return jsonify({
        'area_hectares': area_hectares,
        'area_acres': area_hectares * 2.47105
    })


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)