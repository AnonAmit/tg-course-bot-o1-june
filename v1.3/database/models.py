from pymongo import MongoClient, ASCENDING, DESCENDING
import os
import sys

# Add the project root to the Python path if it's not already discoverable
# This might be needed if you run scripts directly from the database directory
# For an application, manage sys.path at the entry point (e.g., main.py)
# current_dir = os.path.dirname(os.path.abspath(__file__))
# project_root = os.path.dirname(current_dir)
# if project_root not in sys.path:
#    sys.path.append(project_root)

from config.config import MONGODB_URI # Assumes config.py is accessible

_mongo_client = None
_db = None

def get_mongo_client():
    """
    Establishes a connection to MongoDB if one doesn't already exist.
    Returns the MongoDB client instance.
    """
    global _mongo_client
    if _mongo_client is None:
        try:
            _mongo_client = MongoClient(MONGODB_URI)
            # You can add a server_info call to check connection, but be mindful of overhead
            # _mongo_client.admin.command('ping') 
            print("Successfully connected to MongoDB.")
        except Exception as e:
            print(f"Error connecting to MongoDB: {e}")
            # Depending on your app's needs, you might want to raise the exception
            # or handle it by returning None or exiting.
            _mongo_client = None # Ensure it remains None on failure
            raise # Or handle error appropriately
    return _mongo_client

def get_db(database_name="course_delivery_bot_db"): # Default database name
    """
    Gets a specific database from the MongoDB client.
    The database_name can be specified if you use multiple databases,
    or it can be part of your MONGODB_URI.
    If database_name is not in MONGODB_URI, MongoClient connects to default 'test' db
    or the one specified after the slash in the URI.
    Accessing client[database_name] will use that database.
    """
    global _db
    client = get_mongo_client()
    if client is None:
        print("MongoDB client is not available. Cannot get database.")
        return None # Or raise an error

    # If the MONGODB_URI already specifies a database, MongoClient might connect to it directly.
    # mongo_uri_db_name = MongoClient(MONGODB_URI).get_database().name
    # if mongo_uri_db_name and mongo_uri_db_name != 'admin' and mongo_uri_db_name != database_name:
    #     print(f"Warning: MONGODB_URI specifies database '{mongo_uri_db_name}', but requesting '{database_name}'. Using '{database_name}'.")

    # Check if _db is None or if the database name requested has changed
    if _db is None or _db.name != database_name:
        _db = client[database_name]
        print(f"MongoDB database '{_db.name}' obtained.")
    return _db

def create_indexes():
    """
    Creates necessary indexes for the collections if they don't already exist.
    Call this function once during application startup (e.g., in init_db.py).
    """
    db = get_db()
    if db is None:
        print("Cannot create indexes, database not available.")
        return

    try:
        # Users collection
        db.users.create_index("telegram_id", unique=True, name="telegram_id_unique_idx")
        db.users.create_index("username", name="username_idx", sparse=True) # Sparse if username can be null and you want to index only existing ones
        
        # Categories collection
        db.categories.create_index("name", unique=True, name="category_name_unique_idx")
        
        # Courses collection
        db.courses.create_index("title", name="course_title_idx")
        db.courses.create_index("category_id", name="course_category_id_idx") # If you reference categories by ID
        db.courses.create_index("is_free", name="course_is_free_idx")
        db.courses.create_index("is_active", name="course_is_active_idx")

        # Payments collection
        db.payments.create_index("user_id", name="payment_user_id_idx")
        db.payments.create_index("course_id", name="payment_course_id_idx")
        db.payments.create_index("status", name="payment_status_idx")
        db.payments.create_index("payment_method", name="payment_method_idx")

        # Logs collection
        db.logs.create_index("telegram_id", name="log_telegram_id_idx")
        db.logs.create_index("action", name="log_action_idx")
        db.logs.create_index([("timestamp", DESCENDING)], name="log_timestamp_desc_idx")

        # Admins collection
        db.admins.create_index("username", unique=True, name="admin_username_unique_idx")
        db.admins.create_index("email", unique=True, name="admin_email_unique_idx")
        
        # BotSettings collection
        db.bot_settings.create_index("key", unique=True, name="bot_setting_key_unique_idx")

        # CourseRequests collection
        db.course_requests.create_index("user_id", name="course_request_user_id_idx")
        db.course_requests.create_index([("timestamp", DESCENDING)], name="course_request_timestamp_desc_idx")
        
        print("MongoDB indexes ensured for all collections.")
    except Exception as e:
        print(f"An error occurred during index creation: {e}")

# Example of how you might define collection names centrally, though often just accessed via db.collection_name
COLLECTIONS = {
    "users": "users",
    "categories": "categories",
    "courses": "courses",
    "payments": "payments",
    "logs": "logs",
    "admins": "admins",
    "bot_settings": "bot_settings",
    "course_requests": "course_requests"
}

# You would no longer have SQLAlchemy Base, classes like User, Course, etc., or SessionLocal / get_db for sessions.
# All database interactions will now use pymongo directly with the 'db' object obtained from get_db().

# For example, to insert a user:
# user_data = {"telegram_id": "12345", "username": "testuser", ...}
# db = get_db()
# result = db.users.insert_one(user_data)
# print(f"Inserted user with id: {result.inserted_id}")

# To find a user:
# found_user = db.users.find_one({"telegram_id": "12345"})
# if found_user:
#     print(f"Found user: {found_user}") 