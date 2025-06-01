import os
import sys
import hashlib
import datetime

# Ensure the project root is in sys.path for module discovery
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.append(project_root)

# Import new MongoDB related functions and config
from database.models import get_db, create_indexes, COLLECTIONS
from config.config import ADMIN_USERNAME, ADMIN_PASSWORD, ADMIN_EMAIL

def hash_password(password):
    """Simple password hashing"""
    return hashlib.sha256(password.encode()).hexdigest()

def get_or_create_category(db, name):
    """Helper function to get or create a category in MongoDB."""
    categories_collection = db[COLLECTIONS["categories"]]
    category = categories_collection.find_one({"name": name})
    if not category:
        result = categories_collection.insert_one({"name": name, "created_at": datetime.datetime.now(datetime.UTC)})
        print(f"Created category: {name}")
        # Return the newly created document, including its _id
        category = categories_collection.find_one({"_id": result.inserted_id})
    return category

def initialize_database():
    """Initialize the MongoDB database with default admin, sample courses, and ensure indexes."""
    db = get_db() # Get the database instance from models.py
    if db is None:
        print("Failed to get database instance. Initialization aborted.")
        return

    # First, ensure all indexes are created
    print("Ensuring database indexes...")
    create_indexes() # This function is now in models.py

    admins_collection = db[COLLECTIONS["admins"]]
    courses_collection = db[COLLECTIONS["courses"]]
    
    admin_exists = admins_collection.find_one({"username": ADMIN_USERNAME})
    if not admin_exists:
        admin_doc = {
            "username": ADMIN_USERNAME,
            "password_hash": hash_password(ADMIN_PASSWORD),
            "email": ADMIN_EMAIL,
            "created_date": datetime.datetime.now(datetime.UTC),
            "last_login": None 
        }
        admins_collection.insert_one(admin_doc)
        print("Default admin created.")

        # Create Categories
        print("Creating default categories...")
        cat_programming = get_or_create_category(db, "Programming")
        cat_data_science = get_or_create_category(db, "Data Science")
        cat_web_dev = get_or_create_category(db, "Web Development")
        
        # Add sample courses only if admin was just created (implies fresh DB or first setup)
        print("Adding sample courses...")
        sample_courses_data = [
            {
                "title": "Python Programming Basics",
                "description": "Learn Python from scratch with this comprehensive course.",
                "price": 29.99,
                "file_link": "https://drive.google.com/sample_link_1",
                "category_id": cat_programming["_id"] if cat_programming else None, # Store category ObjectId
                "category_name": cat_programming["name"] if cat_programming else None, # Optional: store name for easier display
                "image_link": "https://example.com/python_course.jpg",
                "qr_code_image": None,
                "is_free": False,
                "demo_video_link": None,
                "created_date": datetime.datetime.now(datetime.UTC),
                "updated_date": datetime.datetime.now(datetime.UTC),
                "is_active": True,
                "payment_options": "UPI,PAYPAL" # Example
            },
            {
                "title": "Advanced Machine Learning",
                "description": "Dive deep into machine learning algorithms and techniques.",
                "price": 49.99,
                "file_link": "https://drive.google.com/sample_link_2",
                "category_id": cat_data_science["_id"] if cat_data_science else None,
                "category_name": cat_data_science["name"] if cat_data_science else None,
                "image_link": "https://example.com/ml_course.jpg",
                "is_active": True
            },
            {
                "title": "Web Development with Flask",
                "description": "Build web applications using Flask framework.",
                "price": 39.99,
                "file_link": "https://drive.google.com/sample_link_3",
                "category_id": cat_web_dev["_id"] if cat_web_dev else None,
                "category_name": cat_web_dev["name"] if cat_web_dev else None,
                "image_link": "https://example.com/flask_course.jpg",
                "is_active": True
            }
        ]
        
        if sample_courses_data:
            courses_collection.insert_many(sample_courses_data)
            print(f"{len(sample_courses_data)} sample courses added.")
        
        print("Database initialized with default admin, sample courses/categories, and indexes ensured.")
    else:
        print("Database already initialized (admin exists) or only indexes were updated.")

if __name__ == "__main__":
    print("Running database initialization script...")
    initialize_database()
    # Attempt to close client at the end of script, if client was initialized
    from database.models import _mongo_client
    if _mongo_client:
        _mongo_client.close()
        print("MongoDB connection closed.") 