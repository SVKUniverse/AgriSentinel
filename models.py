from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    parcels = db.relationship('LandParcel', backref='owner', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<User {self.username}>'


class LandParcel(db.Model):
    __tablename__ = 'land_parcels'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    geojson = db.Column(db.Text, nullable=False)  # Store as JSON text
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_computed_at = db.Column(db.DateTime, nullable=True)
    
    # Relationships
    alerts = db.relationship('Alert', backref='parcel', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<LandParcel {self.name}>'


class Alert(db.Model):
    __tablename__ = 'alerts'
    
    id = db.Column(db.Integer, primary_key=True)
    land_id = db.Column(db.Integer, db.ForeignKey('land_parcels.id'), nullable=False, index=True)
    severity = db.Column(db.String(20), nullable=False)  # critical, warning, info
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    
    def __repr__(self):
        return f'<Alert {self.severity}: {self.message[:50]}>'