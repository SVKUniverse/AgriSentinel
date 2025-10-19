from app import app
from models import db

def create_database():
    with app.app_context():
        db.create_all()
        print("Database created successfully!")
        print("Location: agrisentinel.db")
        print("Tables: users, land_parcels, alerts")

if __name__ == '__main__':
    create_database()