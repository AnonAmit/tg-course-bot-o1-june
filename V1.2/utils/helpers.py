import os
import sys
import hashlib
import datetime
import requests
import pyshorteners
import random
import string
from PIL import Image
from io import BytesIO
from bson import ObjectId

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.config import UPLOAD_FOLDER
from database.models import get_db, COLLECTIONS

def log_action(telegram_id, action, ip_address=None, details=None):
    """Log user actions to the MongoDB database"""
    db = get_db()
    if not db:
        print(f"Database not available. Could not log action: {action} for user {telegram_id}")
        return

    logs_collection = db[COLLECTIONS["logs"]]
    log_document = {
        "telegram_id": str(telegram_id),
        "action": action,
        "ip_address": ip_address,
        "details": details,
        "timestamp": datetime.datetime.now(datetime.UTC)
    }
    try:
        logs_collection.insert_one(log_document)
    except Exception as e:
        print(f"Error inserting log into MongoDB: {e}")

def save_payment_proof(telegram_id, file_data, file_extension="jpg"):
    """Save payment proof image to uploads folder"""
    # Create unique filename
    filename = f"{telegram_id}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}_{random_string(8)}.{file_extension}"
    file_path = os.path.join(UPLOAD_FOLDER, filename)
    
    # Save the file
    try:
        if isinstance(file_data, bytes):
            # If file_data is already bytes
            with open(file_path, 'wb') as f:
                f.write(file_data)
        else:
            # If file_data is a file-like object
            with open(file_path, 'wb') as f:
                f.write(file_data.read())
        
        return filename
    except Exception as e:
        print(f"Error saving file: {e}")
        return None

def random_string(length=8):
    """Generate a random string of fixed length"""
    letters = string.ascii_lowercase + string.digits
    return ''.join(random.choice(letters) for i in range(length))

def shorten_url(url):
    """Shorten a URL using TinyURL"""
    try:
        s = pyshorteners.Shortener()
        return s.tinyurl.short(url)
    except Exception as e:
        print(f"Error shortening URL: {e}")
        return url

def is_valid_image(file_data):
    """Check if the file is a valid image"""
    try:
        img = Image.open(BytesIO(file_data))
        img.verify()  # Verify it's an image
        return True
    except Exception:
        return False

def is_spam(text):
    """Simple spam detection"""
    # Check for common spam indicators
    spam_keywords = ["casino", "porn", "sex", "viagra", "lottery", "free money", "bitcoin generator"]
    text_lower = text.lower()
    
    for keyword in spam_keywords:
        if keyword in text_lower:
            return True
    
    # Check for excessive use of special characters
    special_chars = "!@#$%^&*()_+={}[]|\\:;'<>,.?/"
    special_char_count = sum(1 for c in text if c in special_chars)
    
    if special_char_count > len(text) * 0.3:  # If more than 30% are special characters
        return True
    
    return False

def detect_duplicate_payment(image_data, user_id):
    """Simple duplicate payment detection based on image hash"""
    image_hash = hashlib.md5(image_data).hexdigest()
    # TODO: Compare with previously submitted payment proofs (e.g., store hashes in payment docs)
    return False

def format_course_info(course_doc):
    """Format course information from a MongoDB document for display in Telegram"""
    # Assumes course_doc is a dictionary (MongoDB document)
    # category_name should be denormalized in course_doc or fetched separately if only category_id is present
    category_name = course_doc.get("category_name", "Uncategorized") 
    if not category_name and course_doc.get("category_id"):
        # Fallback: if category_name is not in course_doc, try to fetch it
        # This is less efficient and ideally category_name is denormalized
        db = get_db()
        if db:
            categories_collection = db[COLLECTIONS["categories"]]
            cat_doc = categories_collection.find_one({"_id": ObjectId(course_doc["category_id"])})
            if cat_doc:
                category_name = cat_doc.get("name", "Uncategorized")

    title = course_doc.get("title", "N/A")
    description = course_doc.get("description", "N/A")
    price = course_doc.get("price", 0.0)
    
    course_text = (
        f'📚 **{title}**\n\n'
        f'📝 **Description:** {description}\n\n'
        f'💰 **Price:** ₹{price:.2f}\n\n' # Assuming price is float
        f'🏷️ **Category:** {category_name}'
    )
    
    return course_text 