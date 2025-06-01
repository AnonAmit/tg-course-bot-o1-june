import os
import sys
import datetime
import hashlib
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from bson import ObjectId

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.config import ADMIN_USERNAME, ADMIN_PASSWORD, UPLOAD_FOLDER
from database.models import get_db, COLLECTIONS

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'dev_secret_key')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload size

# Ensure the upload folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Allowed file extensions for security
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# User loader for Flask-Login
class AdminUser(UserMixin):
    def __init__(self, admin_id, username):
        self.id = str(admin_id)
        self.username = username

@login_manager.user_loader
def load_user(admin_id_str):
    try:
        admin_oid = ObjectId(admin_id_str)
    except Exception:
        return None
        
    db = get_db()
    if not db: return None
    admins_collection = db[COLLECTIONS["admins"]]
    admin_doc = admins_collection.find_one({"_id": admin_oid})
    
    if admin_doc:
        return AdminUser(admin_doc["_id"], admin_doc["username"])
    return None

# Helper functions
def hash_password(password):
    """Simple password hashing"""
    return hashlib.sha256(password.encode()).hexdigest()

def get_stats():
    """Get system statistics using MongoDB"""
    db = get_db()
    if not db:
        # Return empty or default stats if DB is not available
        return {
            'total_users': 0, 'total_courses': 0, 'total_payments': 0,
            'pending_payments': 0, 'approved_payments': 0, 'revenue': 0,
            'recent_payments': []
        }

    users_collection = db[COLLECTIONS["users"]]
    courses_collection = db[COLLECTIONS["courses"]]
    payments_collection = db[COLLECTIONS["payments"]]

    total_users = users_collection.count_documents({})
    total_courses = courses_collection.count_documents({})
    total_payments = payments_collection.count_documents({})
    
    pending_payments = payments_collection.count_documents({"status": 'pending'})
    approved_payments = payments_collection.count_documents({"status": 'approved'})
    
    # Calculate revenue using MongoDB aggregation pipeline
    revenue_pipeline = [
        {"$match": {"status": "approved"}},
        {"$group": {"_id": None, "total_revenue": {"$sum": "$amount"}}}
    ]
    revenue_result = list(payments_collection.aggregate(revenue_pipeline))
    revenue = revenue_result[0]["total_revenue"] if revenue_result else 0
    
    # Recent payments (ensure submission_date is stored as datetime object in MongoDB for correct sorting)
    # In init_db.py, we used datetime.datetime.now(datetime.UTC), which is good.
    recent_payments_cursor = payments_collection.find({}).sort("submission_date", -1).limit(5)
    recent_payments_list = []
    for payment_doc in recent_payments_cursor:
        # We need to fetch related course and user information if needed for display
        # This is where MongoDB differs from SQLAlchemy's automatic relationships
        # For now, just passing the payment_doc. We might need to adjust this later
        # based on what 'dashboard.html' template expects.
        # Example: Fetch course title
        course_doc = courses_collection.find_one({"_id": payment_doc.get("course_id")})
        payment_doc['course_title'] = course_doc['title'] if course_doc else 'N/A'
        user_doc = users_collection.find_one({"_id": payment_doc.get("user_id")})
        payment_doc['user_identifier'] = user_doc.get('username', user_doc.get('telegram_id')) if user_doc else 'N/A'
        recent_payments_list.append(payment_doc)
    
    return {
        'total_users': total_users,
        'total_courses': total_courses,
        'total_payments': total_payments,
        'pending_payments': pending_payments,
        'approved_payments': approved_payments,
        'revenue': revenue,
        'recent_payments': recent_payments_list
    }

def get_user_logs(telegram_id):
    """Get logs for a specific user"""
    db = get_db()
    logs = db.query(Log).filter_by(telegram_id=telegram_id).order_by(Log.timestamp.desc()).limit(50).all()
    return logs

def allowed_file(filename):
    """Check if a file has an allowed extension"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Routes
@app.route('/')
def index():
    """Redirect to login or dashboard"""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Admin login"""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        db = get_db()
        if not db:
            flash('Database connection error.', 'danger')
            return render_template('login.html')
            
        admins_collection = db[COLLECTIONS["admins"]]
        admin_doc = admins_collection.find_one({"username": username})
        
        if admin_doc and admin_doc["password_hash"] == hash_password(password):
            admins_collection.update_one(
                {"_id": admin_doc["_id"]},
                {"$set": {"last_login": datetime.datetime.now(datetime.UTC)}}
            )
            
            user_to_login = AdminUser(admin_doc["_id"], admin_doc["username"])
            login_user(user_to_login)
            
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        
        flash('Invalid username or password.', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    """Admin logout"""
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    """Admin dashboard"""
    stats = get_stats()
    return render_template('dashboard.html', stats=stats)

@app.route('/courses')
@login_required
def courses():
    """Course management using MongoDB"""
    search_query = request.args.get('search', '')
    db = get_db()
    if not db: 
        flash('Database error.', 'danger')
        return render_template('courses.html', courses=[], search_query=search_query, error=True)

    courses_collection = db[COLLECTIONS["courses"]]
    query_filter = {}

    if search_query:
        # Search in course title or category name (if category_name is stored in course doc)
        # For a more robust category search, you might need to search categories first then courses by category_id
        query_filter["$or"] = [
            {"title": {"$regex": search_query, "$options": "i"}},
            {"description": {"$regex": search_query, "$options": "i"}}, # Added description to search
            {"category_name": {"$regex": search_query, "$options": "i"}} # Assumes category_name is denormalized
        ]
    
    # Fetch courses and include category name (if category_id exists)
    # This is a simple client-side join. For complex scenarios, $lookup in aggregation is better.
    courses_list = []
    categories_collection = db[COLLECTIONS["categories"]]
    for course_doc in courses_collection.find(query_filter).sort("created_date", -1):
        if course_doc.get("category_id"):
            category_doc = categories_collection.find_one({"_id": ObjectId(course_doc["category_id"])})
            course_doc["category_name_resolved"] = category_doc["name"] if category_doc else "N/A"
        else:
            course_doc["category_name_resolved"] = "N/A"
        courses_list.append(course_doc)
    
    return render_template('courses.html', courses=courses_list, search_query=search_query)

@app.route('/course/add', methods=['GET', 'POST'])
@login_required
def add_course():
    """Add a new course using MongoDB"""
    db = get_db()
    if not db: 
        flash('Database error.', 'danger')
        return redirect(url_for('courses'))

    categories_collection = db[COLLECTIONS["categories"]]
    courses_collection = db[COLLECTIONS["courses"]]
    
    categories_list = list(categories_collection.find({}).sort("name", 1))

    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        price_str = request.form.get('price', '0')
        try:
            price = float(price_str)
        except ValueError:
            flash('Invalid price format.', 'danger')
            return render_template('course_form.html', course=None, categories=categories_list, request_form=request.form)
            
        file_link = request.form.get('file_link')
        category_id_str = request.form.get('category_id')
        category_oid = ObjectId(category_id_str) if category_id_str else None
        category_name = None
        if category_oid:
            cat_doc = categories_collection.find_one({"_id": category_oid})
            if cat_doc: category_name = cat_doc.get('name')

        image_link = request.form.get('image_link')
        payment_options = request.form.getlist('payment_options')
        payment_options_str = ','.join(payment_options) if payment_options else None
        qr_code_image = request.form.get('qr_code_image')
        is_free = 'is_free' in request.form
        demo_video_link = request.form.get('demo_video_link')

        if not title or not file_link or (not is_free and price <= 0):
            flash('Please fill all required fields. Price must be > 0 unless course is free.', 'danger')
            return render_template('course_form.html', course=None, categories=categories_list, request_form=request.form)
        
        image_upload_url = image_link # Default to existing link if any
        image_file = request.files.get('image_upload')
        if image_file and image_file.filename and allowed_file(image_file.filename):
            filename = secure_filename(image_file.filename)
            unique_filename = f"{datetime.datetime.now(datetime.UTC).strftime('%Y%m%d%H%M%S%f')}_{filename}"
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
            try:
                image_file.save(image_path)
                image_upload_url = url_for('uploaded_file', filename=unique_filename, _external=True)
            except Exception as e:
                flash(f'Error saving image: {e}', 'danger')
        elif image_file and image_file.filename and not allowed_file(image_file.filename):
            flash('Invalid file type for image. Only PNG, JPG, JPEG, GIF, WEBP allowed.', 'danger')
            return render_template('course_form.html', course=None, categories=categories_list, request_form=request.form)

        course_doc = {
            "title": title,
            "description": description,
            "price": price,
            "file_link": file_link,
            "category_id": category_oid,
            "category_name": category_name, # Denormalizing category name for easier searching/listing
            "image_link": image_upload_url, # Use uploaded image URL or provided link
            "is_active": True,
            "payment_options": payment_options_str,
            "qr_code_image": qr_code_image if qr_code_image else None,
            "is_free": is_free,
            "demo_video_link": demo_video_link if demo_video_link else None,
            "created_date": datetime.datetime.now(datetime.UTC),
            "updated_date": datetime.datetime.now(datetime.UTC)
        }
        
        try:
            courses_collection.insert_one(course_doc)
            flash('Course added successfully!', 'success')
            return redirect(url_for('courses'))
        except Exception as e:
            flash(f'Error adding course: {e}', 'danger')
    
    return render_template('course_form.html', course=None, categories=categories_list, request_form=request.form if request.method == 'POST' else None)

@app.route('/course/edit/<int:course_id>', methods=['GET', 'POST'])
@login_required
def edit_course(course_id):
    """Edit an existing course"""
    db = get_db()
    course = db.query(Course).filter_by(id=course_id).first()
    categories_list = db.query(Category).order_by(Category.name).all()

    if not course:
        flash('Course not found.', 'danger')
        return redirect(url_for('courses'))
    
    if request.method == 'POST':
        course.title = request.form.get('title')
        course.description = request.form.get('description')
        course.price = float(request.form.get('price'))
        course.file_link = request.form.get('file_link')
        category_id = request.form.get('category_id')
        course.category_id = int(category_id) if category_id else None
        
        # Get payment options as a list
        payment_options = request.form.getlist('payment_options')
        course.payment_options = ','.join(payment_options) if payment_options else None

        course.qr_code_image = request.form.get('qr_code_image')
        if course.qr_code_image == "": # Handle empty string from select
            course.qr_code_image = None
        course.is_free = 'is_free' in request.form
        course.demo_video_link = request.form.get('demo_video_link')
        if course.demo_video_link == "":
            course.demo_video_link = None

        if not course.is_free and course.price <= 0:
            flash('Price must be greater than 0 unless the course is marked as free.', 'danger')
            return redirect(url_for('edit_course', course_id=course_id))
        
        # Keep existing image_link as default
        image_link = request.form.get('image_link')
        if not image_link:
            image_link = course.image_link
        
        # Handle image upload if provided
        image_file = request.files.get('image_upload')
        if image_file and image_file.filename and allowed_file(image_file.filename):
            # Secure the filename
            filename = secure_filename(image_file.filename)
            # Create a unique filename to prevent overwriting
            unique_filename = f"{datetime.datetime.now(datetime.UTC).strftime('%Y%m%d%H%M%S')}_{filename}"
            # Save the file
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
            image_file.save(image_path)
            # Set the image link to the uploaded file URL
            image_link = url_for('uploaded_file', filename=unique_filename, _external=True)
        elif image_file and image_file.filename and not allowed_file(image_file.filename):
            flash('Invalid file type. Only images (PNG, JPG, JPEG, GIF, WEBP) are allowed.', 'danger')
            return redirect(url_for('edit_course', course_id=course_id))
        
        # Update the image link (either from upload or form input)
        course.image_link = image_link
        course.is_active = 'is_active' in request.form
        # course.updated_date is automatically handled by the model's onupdate
        
        db.commit()
        
        flash('Course updated successfully!', 'success')
        return redirect(url_for('courses'))
    
    return render_template('course_form.html', course=course, categories=categories_list)

@app.route('/course/delete/<int:course_id>')
@login_required
def delete_course(course_id):
    """Delete a course"""
    db = get_db()
    course = db.query(Course).filter_by(id=course_id).first()
    
    if not course:
        flash('Course not found.', 'danger')
        return redirect(url_for('courses'))
    
    # Check if there are any payments associated with this course
    payment_count = db.query(Payment).filter_by(course_id=course_id).count()
    if payment_count > 0:
        flash(f'Cannot delete this course because it has {payment_count} associated payments. Consider marking it as inactive instead.', 'danger')
        return redirect(url_for('courses'))
    
    # If no payments are associated, proceed with deletion
    db.delete(course)
    db.commit()
    flash('Course deleted successfully!', 'success')
    
    return redirect(url_for('courses'))

@app.route('/payments')
@login_required
def payments():
    """Payment management using MongoDB"""
    db = get_db()
    if not db: 
        flash('Database error.', 'danger')
        return render_template('payments.html', payments_list=[], current_status=request.args.get('status', ''), search_query=request.args.get('search', ''), error=True)

    payments_collection = db[COLLECTIONS["payments"]]
    users_collection = db[COLLECTIONS["users"]]
    courses_collection = db[COLLECTIONS["courses"]]

    status_filter = request.args.get('status', '')
    search_query = request.args.get('search', '')

    query_filter = {}
    if status_filter:
        query_filter["status"] = status_filter
    
    # Enhanced search: This part is tricky due to needing data from related collections.
    # We will first try to find matching user_ids or course_ids based on the search query,
    # then use those ObjectIds in the payments query.
    # This is a more robust approach than trying to regex match ObjectIds directly.
    candidate_user_ids = []
    candidate_course_ids = []

    if search_query:
        # Search for users by telegram_id or username
        user_search_filter = {
            "$or": [
                {"telegram_id": {"$regex": search_query, "$options": "i"}},
                {"username": {"$regex": search_query, "$options": "i"}}
            ]
        }
        for user_doc in users_collection.find(user_search_filter, {"_id": 1}):
            candidate_user_ids.append(user_doc["_id"])

        # Search for courses by title
        course_search_filter = {"title": {"$regex": search_query, "$options": "i"}}
        for course_doc in courses_collection.find(course_search_filter, {"_id": 1}):
            candidate_course_ids.append(course_doc["_id"])
        
        search_conditions = []
        if candidate_user_ids:
            search_conditions.append({"user_id": {"$in": candidate_user_ids}})
        if candidate_course_ids:
            search_conditions.append({"course_id": {"$in": candidate_course_ids}})
        
        # Allow searching by payment_method or other direct payment fields if needed
        # For example, if search_query could be a payment method string:
        # search_conditions.append({"payment_method": {"$regex": search_query, "$options": "i"}})
        
        # If search_query might be an ObjectId string itself (e.g. for payment_id, user_id, course_id)
        try:
            possible_oid = ObjectId(search_query)
            search_conditions.append({"_id": possible_oid})
            if not candidate_user_ids: # if user search didn't yield results, try direct id match
                 search_conditions.append({"user_id": possible_oid}) 
            if not candidate_course_ids: # if course search didn't yield results, try direct id match
                 search_conditions.append({"course_id": possible_oid})
        except Exception:
            pass # Not a valid ObjectId, ignore

        if search_conditions:
            query_filter["$or"] = search_conditions
        elif not query_filter: # No status filter and search yielded no conditions means no results for search
            # To ensure no results if search_query was provided but found nothing relevant to link to payments
            # we can add a condition that will not be met, or simply return empty list later.
            # For now, if search_conditions is empty and query_filter was based on search, we effectively search all if status_filter is also empty.
            # If search_query was given and no conditions were built, it implies the search didn't match any users/courses.
            # We should probably show no payments in this case, unless status_filter is also active.
            if search_query and not status_filter:
                return render_template('payments.html', payments_list=[], current_status=status_filter, search_query=search_query)

    payments_list_cursor = payments_collection.find(query_filter).sort("submission_date", -1)
    
    payments_display_list = []
    for p_doc in payments_list_cursor:
        if p_doc.get("user_id"):
            user = users_collection.find_one({"_id": ObjectId(p_doc["user_id"])})
            p_doc["user_identifier"] = user.get("username") or user.get("telegram_id", "Unknown User") if user else "Unknown User"
        else:
            p_doc["user_identifier"] = "N/A"
        
        if p_doc.get("course_id"):
            course = courses_collection.find_one({"_id": ObjectId(p_doc["course_id"])})
            p_doc["course_title"] = course["title"] if course else "Unknown Course"
        else:
            p_doc["course_title"] = "N/A"
        payments_display_list.append(p_doc)
            
    return render_template('payments.html', payments_list=payments_display_list, current_status=status_filter, search_query=search_query)

@app.route('/payment/<path:payment_id_str>')
@login_required
def payment_detail(payment_id_str):
    """Payment detail view using MongoDB"""
    db = get_db()
    if not db: 
        flash('Database error.', 'danger')
        return redirect(url_for('payments'))
    try:
        payment_oid = ObjectId(payment_id_str)
    except Exception:
        flash('Invalid payment ID format.', 'danger')
        return redirect(url_for('payments'))

    payments_collection = db[COLLECTIONS["payments"]]
    payment = payments_collection.find_one({"_id": payment_oid})

    if not payment:
        flash('Payment not found.', 'danger')
        return redirect(url_for('payments'))

    if payment.get("user_id"):
        users_collection = db[COLLECTIONS["users"]]
        user = users_collection.find_one({"_id": ObjectId(payment["user_id"])})
        payment["user_obj"] = user # Pass full user doc for template flexibility
        payment["user_identifier"] = user.get("username") or user.get("telegram_id", "Unknown User") if user else "Unknown User"

    if payment.get("course_id"):
        courses_collection = db[COLLECTIONS["courses"]]
        course = courses_collection.find_one({"_id": ObjectId(payment["course_id"])})
        payment["course_obj"] = course # Pass full course doc
        payment["course_title"] = course["title"] if course else "Unknown Course"

    return render_template('payment_detail.html', payment=payment)

@app.route('/payment/approve/<path:payment_id_str>')
@login_required
def approve_payment(payment_id_str):
    """Approve a payment using MongoDB"""
    db = get_db()
    if not db: 
        flash('Database error.', 'danger')
        return redirect(request.referrer or url_for('payments'))
    try:
        payment_oid = ObjectId(payment_id_str)
    except Exception:
        flash('Invalid payment ID format.', 'danger')
        return redirect(request.referrer or url_for('payments'))

    payments_collection = db[COLLECTIONS["payments"]]
    
    # Ensure payment proof exists if it's a required step before approval for some methods
    # payment_doc = payments_collection.find_one({"_id": payment_oid})
    # if payment_doc and payment_doc.get('payment_method') != 'COD' and not payment_doc.get('payment_proof') and not payment_doc.get('is_free'):
    #     flash('Cannot approve: Payment proof is missing.', 'warning')
    #     return redirect(request.referrer or url_for('payments'))
        
    result = payments_collection.update_one(
        {"_id": payment_oid, "status": "pending"}, 
        {"$set": {"status": "approved", "approval_date": datetime.datetime.now(datetime.UTC)}}
    )

    if result.modified_count > 0:
        flash('Payment approved successfully!', 'success')
        # TODO: Add logic to notify the user or grant course access via the bot
        # Example: grant_course_access_to_user(user_id, course_id)
    elif payments_collection.find_one({"_id": payment_oid, "status": "approved"}):
        flash('Payment was already approved.', 'info')
    else:
        flash('Payment not found or could not be approved (e.g., not pending or already processed).', 'warning')
    return redirect(request.referrer or url_for('payments'))

@app.route('/payment/reject/<path:payment_id_str>')
@login_required
def reject_payment(payment_id_str):
    """Reject a payment using MongoDB"""
    db = get_db()
    if not db: 
        flash('Database error.', 'danger')
        return redirect(request.referrer or url_for('payments'))
    try:
        payment_oid = ObjectId(payment_id_str)
    except Exception:
        flash('Invalid payment ID format.', 'danger')
        return redirect(request.referrer or url_for('payments'))

    payments_collection = db[COLLECTIONS["payments"]]
    result = payments_collection.update_one(
        {"_id": payment_oid, "status": "pending"}, 
        {"$set": {"status": "rejected", "approval_date": datetime.datetime.now(datetime.UTC)}} # approval_date here acts more like action_date
    )

    if result.modified_count > 0:
        flash('Payment rejected successfully!', 'success')
    elif payments_collection.find_one({"_id": payment_oid, "status": "rejected"}):
        flash('Payment was already rejected.', 'info')
    else:
        flash('Payment not found or could not be rejected (e.g., not pending or already processed).', 'warning')
    return redirect(request.referrer or url_for('payments'))

@app.route('/users')
@login_required
def users():
    """User management using MongoDB"""
    db = get_db()
    if not db: 
        flash('Database error.', 'danger')
        return render_template('users.html', users_list=[], error=True)

    users_collection = db[COLLECTIONS["users"]]
    search_query = request.args.get('search', '')
    query_filter = {}

    if search_query:
        # Search by telegram_id (exact match usually), username, first_name, or last_name (regex)
        # If search_query could be an ObjectId string for _id
        search_conditions = [
            {"username": {"$regex": search_query, "$options": "i"}},
            {"first_name": {"$regex": search_query, "$options": "i"}},
            {"last_name": {"$regex": search_query, "$options": "i"}},
            {"telegram_id": search_query} # Assuming telegram_id is usually an exact match string
        ]
        try:
            possible_oid = ObjectId(search_query)
            search_conditions.append({"_id": possible_oid})
        except Exception:
            pass # Not a valid ObjectId
        query_filter["$or"] = search_conditions
        
    users_list = list(users_collection.find(query_filter).sort("joined_date", -1))
    return render_template('users.html', users_list=users_list, search_query=search_query)

@app.route('/user/<path:user_id_str>')
@login_required
def user_detail(user_id_str):
    """User detail view using MongoDB"""
    db = get_db()
    if not db: 
        flash('Database error.', 'danger')
        return redirect(url_for('users'))
    try:
        user_oid = ObjectId(user_id_str)
    except Exception:
        flash('Invalid user ID format.', 'danger')
        return redirect(url_for('users'))

    users_collection = db[COLLECTIONS["users"]]
    user = users_collection.find_one({"_id": user_oid})

    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('users'))

    # Get user logs (assuming telegram_id is stored in logs and is a string)
    logs_collection = db[COLLECTIONS["logs"]]
    user_logs = []
    if user.get("telegram_id"):
        user_logs = list(logs_collection.find({"telegram_id": user.get("telegram_id")}).sort("timestamp", -1).limit(50))
    
    # Get user payments
    payments_collection = db[COLLECTIONS["payments"]]
    user_payments = list(payments_collection.find({"user_id": user_oid}).sort("submission_date", -1))
    
    courses_collection = db[COLLECTIONS["courses"]]
    for p_doc in user_payments:
        if p_doc.get("course_id"):
            course = courses_collection.find_one({"_id": ObjectId(p_doc["course_id"])})
            p_doc["course_title"] = course["title"] if course else "Unknown Course"
        else:
            p_doc["course_title"] = "N/A"

    return render_template('user_detail.html', user=user, logs=user_logs, payments=user_payments)

@app.route('/user/ban/<path:user_id_str>', methods=['POST'])
@login_required
def ban_user(user_id_str):
    """Ban a user using MongoDB"""
    db = get_db()
    if not db: 
        flash('Database error.', 'danger')
        return redirect(request.referrer or url_for('users'))
    try:
        user_oid = ObjectId(user_id_str)
    except Exception:
        flash('Invalid user ID format.', 'danger')
        return redirect(request.referrer or url_for('users'))

    reason = request.form.get('ban_reason', 'No reason provided.')
    users_collection = db[COLLECTIONS["users"]]
    result = users_collection.update_one(
        {"_id": user_oid},
        {"$set": {"is_banned": True, "ban_reason": reason}}
    )
    if result.modified_count > 0:
        flash('User banned successfully.', 'success')
    else:
        flash('User not found or already banned.', 'warning')
    return redirect(request.referrer or url_for('user_detail', user_id_str=user_id_str))

@app.route('/user/unban/<path:user_id_str>') # Changed to GET for simplicity, consider POST for consistency
@login_required
def unban_user(user_id_str):
    """Unban a user using MongoDB"""
    db = get_db()
    if not db: 
        flash('Database error.', 'danger')
        return redirect(request.referrer or url_for('users'))
    try:
        user_oid = ObjectId(user_id_str)
    except Exception:
        flash('Invalid user ID format.', 'danger')
        return redirect(request.referrer or url_for('users'))

    users_collection = db[COLLECTIONS["users"]]
    result = users_collection.update_one(
        {"_id": user_oid},
        {"$set": {"is_banned": False, "ban_reason": None}}
    )
    if result.modified_count > 0:
        flash('User unbanned successfully.', 'success')
    else:
        flash('User not found or not banned.', 'warning')
    return redirect(request.referrer or url_for('user_detail', user_id_str=user_id_str))

@app.route('/logs')
@login_required
def logs():
    """View system logs using MongoDB"""
    db = get_db()
    if not db: 
        flash('Database error.', 'danger')
        return render_template('logs.html', logs_list=[], error=True)

    logs_collection = db[COLLECTIONS["logs"]]
    
    search_query = request.args.get('search', '') # Search by telegram_id or action
    page = request.args.get('page', 1, type=int)
    per_page = 50 # Number of logs per page

    query_filter = {}
    if search_query:
        query_filter["$or"] = [
            {"telegram_id": {"$regex": search_query, "$options": "i"}},
            {"action": {"$regex": search_query, "$options": "i"}},
            {"details": {"$regex": search_query, "$options": "i"}} # Added details to search
        ]
        
    total_logs = logs_collection.count_documents(query_filter)
    logs_list = list(logs_collection.find(query_filter)
                                 .sort("timestamp", -1)
                                 .skip((page - 1) * per_page)
                                 .limit(per_page))
    
    total_pages = (total_logs + per_page - 1) // per_page

    return render_template('logs.html', logs_list=logs_list, search_query=search_query,
                           current_page=page, total_pages=total_pages)

@app.route('/uploads/<filename>')
#@login_required # Usually, uploaded files might be public or served differently. Review if login is strictly needed.
def uploaded_file(filename):
    """Serve uploaded files. Ensure this is secure and only serves allowed files/paths."""
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/course/<int:course_id>')
@login_required
def course_detail(course_id):
    """View course details"""
    db = get_db()
    course = db.query(Course).filter_by(id=course_id).first()
    
    if not course:
        flash('Course not found.', 'danger')
        return redirect(url_for('courses'))
    
    associated_payments = db.query(Payment).filter_by(course_id=course_id).all()
    return render_template('course_detail.html', course=course, payments=associated_payments)

@app.route('/fix-gift-codes')
@login_required
def fix_gift_codes():
    """Fix any masked gift card codes in the MongoDB database"""
    db = get_db()
    if not db:
        flash('Database error.', 'danger')
        return redirect(url_for('payments'))

    payments_collection = db[COLLECTIONS["payments"]]
    
    # Find gift card payments where details might be masked (contains '*')
    # We only want to update if it hasn't already been marked for manual update.
    query_filter = {
        "payment_method": "gift", 
        "details": {"$regex": ".*\*.*"}, # Contains an asterisk
        "details": {"$not": {"$regex": "^NEEDS MANUAL UPDATE"}} # Does not already start with the warning
    }
    
    gift_payments_cursor = payments_collection.find(query_filter)
    
    fixed_count = 0
    for payment_doc in gift_payments_cursor:
        original_details = payment_doc.get("details", "")
        new_details = "NEEDS MANUAL UPDATE - Was masked: " + original_details
        
        result = payments_collection.update_one(
            {"_id": payment_doc["_id"]},
            {"$set": {"details": new_details}}
        )
        if result.modified_count > 0:
            fixed_count += 1
    
    if fixed_count > 0:
        flash(f'Marked {fixed_count} potentially masked gift card codes for manual update.', 'warning')
    else:
        flash('No new masked gift card codes found needing an update.', 'info')
    
    return redirect(url_for('payments'))

# CATEGORY ROUTES
@app.route('/categories')
@login_required
def categories():
    """Category management using MongoDB"""
    db = get_db()
    if not db: 
        flash('Database error.', 'danger')
        return render_template('categories.html', categories_list=[], error=True)
    
    categories_collection = db[COLLECTIONS["categories"]]
    # For each category, count how many courses are associated with it
    categories_list_agg = list(categories_collection.aggregate([
        {
            "$lookup": {
                "from": COLLECTIONS["courses"],
                "localField": "_id",
                "foreignField": "category_id",
                "as": "courses"
            }
        },
        {
            "$addFields": {
                "course_count": {"$size": "$courses"}
            }
        },
        {
            "$project": {
                "courses": 0 # Remove the courses array from the result if not needed
            }
        },
        {
            "$sort": {"name": 1}
        }
    ]))
    return render_template('categories.html', categories_list=categories_list_agg)

@app.route('/category/add', methods=['GET', 'POST'])
@login_required
def add_category():
    """Add a new category using MongoDB"""
    db = get_db()
    if not db: 
        flash('Database error.', 'danger')
        return redirect(url_for('categories'))

    categories_collection = db[COLLECTIONS["categories"]]
    if request.method == 'POST':
        name = request.form.get('name')
        if not name:
            flash('Category name is required.', 'danger')
        else:
            try:
                # Index on 'name' is unique, so insert_one will fail if name exists
                categories_collection.insert_one({"name": name, "created_at": datetime.datetime.now(datetime.UTC)})
                flash('Category added successfully!', 'success')
                return redirect(url_for('categories'))
            except Exception as e: # pymongo.errors.DuplicateKeyError for unique constraint
                if "duplicate key error" in str(e).lower():
                    flash(f'Category "{name}" already exists.', 'warning')
                else:
                    flash(f'Error adding category: {e}', 'danger')
    return render_template('category_form.html', category=None)

@app.route('/category/edit/<path:category_id_str>', methods=['GET', 'POST'])
@login_required
def edit_category(category_id_str):
    """Edit an existing category using MongoDB"""
    db = get_db()
    if not db: 
        flash('Database error.', 'danger')
        return redirect(url_for('categories'))
    try:
        category_oid = ObjectId(category_id_str)
    except Exception:
        flash('Invalid category ID format.', 'danger')
        return redirect(url_for('categories'))

    categories_collection = db[COLLECTIONS["categories"]]
    category = categories_collection.find_one({"_id": category_oid})

    if not category:
        flash('Category not found.', 'danger')
        return redirect(url_for('categories'))

    if request.method == 'POST':
        new_name = request.form.get('name')
        if not new_name:
            flash('Category name is required.', 'danger')
        elif new_name == category.get('name'):
            flash('No changes made to category name.', 'info')
        else:
            try:
                # Check if new name already exists for another category
                existing_with_new_name = categories_collection.find_one({"name": new_name, "_id": {"$ne": category_oid}})
                if existing_with_new_name:
                    flash(f'Category name "{new_name}" already exists for another category.', 'warning')
                else:
                    result = categories_collection.update_one({"_id": category_oid}, {"$set": {"name": new_name, "updated_at": datetime.datetime.now(datetime.UTC)}})
                    if result.modified_count > 0:
                        # Update denormalized category_name in courses
                        courses_collection = db[COLLECTIONS["courses"]]
                        courses_collection.update_many({"category_id": category_oid}, {"$set": {"category_name": new_name}})
                        flash('Category updated successfully! Associated courses also updated.', 'success')
                    else:
                        flash('Could not update category or no changes made.', 'warning')
                    return redirect(url_for('categories'))
            except Exception as e:
                if "duplicate key error" in str(e).lower(): # Should be caught by check above, but as a fallback
                    flash(f'Category "{new_name}" already exists.', 'warning')
                else:
                    flash(f'Error updating category: {e}', 'danger')
    return render_template('category_form.html', category=category)

@app.route('/category/delete/<path:category_id_str>')
@login_required
def delete_category(category_id_str):
    """Delete a category using MongoDB"""
    db = get_db()
    if not db: 
        flash('Database error.', 'danger')
        return redirect(url_for('categories'))
    try:
        category_oid = ObjectId(category_id_str)
    except Exception:
        flash('Invalid category ID format.', 'danger')
        return redirect(url_for('categories'))

    categories_collection = db[COLLECTIONS["categories"]]
    courses_collection = db[COLLECTIONS["courses"]]

    # Check if any course is using this category
    associated_courses_count = courses_collection.count_documents({"category_id": category_oid})
    if associated_courses_count > 0:
        flash(f'Cannot delete category: {associated_courses_count} course(s) are linked to it. Please reassign them first.', 'danger')
        return redirect(url_for('categories'))

    result = categories_collection.delete_one({"_id": category_oid})
    if result.deleted_count > 0:
        flash('Category deleted successfully!', 'success')
    else:
        flash('Category not found or already deleted.', 'warning')
    return redirect(url_for('categories'))

# BOT SETTINGS ROUTE
@app.route('/settings', methods=['GET', 'POST'])
@login_required
def bot_settings():
    """Manage bot settings using MongoDB"""
    db = get_db()
    if not db: 
        flash('Database error.', 'danger')
        return render_template('settings.html', settings_dict={}, error=True)

    settings_collection = db[COLLECTIONS["bot_settings"]]
    if request.method == 'POST':
        for key, value in request.form.items():
            # Use upsert to create setting if not exist, or update if exist
            settings_collection.update_one({"key": key}, {"$set": {"value": value}}, upsert=True)
        flash('Settings updated successfully!', 'success')
        return redirect(url_for('bot_settings'))

    settings_docs = list(settings_collection.find({}))
    settings_dict = {doc['key']: doc['value'] for doc in settings_docs}
    
    # Define expected keys to ensure form fields are present, even if no value in DB
    # These keys should match the 'name' attributes of your form inputs in settings.html
    expected_keys = [
        'WELCOME_MESSAGE', 'AUTO_DELETE_SECONDS', 'AUTO_APPROVE', 'BOT_PASSWORD',
        'UPI_ID', 'CRYPTO_ADDRESS', 'PAYPAL_ID', 'COD_ENABLED', 'GIFT_CARD_ENABLED',
        'BOT_NAME', 'ADMIN_EMAIL', 'NOTIFICATION_EMAIL', 'ENABLE_EMAIL_NOTIFICATION'
        # Add any other setting keys your form uses
    ]
    for ek in expected_keys:
        if ek not in settings_dict:
            settings_dict[ek] = '' # Default to empty string if not found
            
    return render_template('settings.html', settings_dict=settings_dict)

# COURSE REQUEST ROUTES
@app.route('/course-requests')
@login_required
def course_requests_list():
    """List course requests using MongoDB"""
    db = get_db()
    if not db: 
        flash('Database error.', 'danger')
        return render_template('course_requests.html', requests_list=[], error=True)

    course_requests_collection = db[COLLECTIONS["course_requests"]]
    users_collection = db[COLLECTIONS["users"]]
    
    requests_cursor = course_requests_collection.find({}).sort("timestamp", -1)
    requests_display_list = []
    for req_doc in requests_cursor:
        if req_doc.get("user_id"):
            user = users_collection.find_one({"_id": ObjectId(req_doc["user_id"])})
            req_doc["user_identifier"] = user.get("username") or user.get("telegram_id", "Unknown User") if user else "Unknown User"
        else:
            req_doc["user_identifier"] = "N/A"
        requests_display_list.append(req_doc)
        
    return render_template('course_requests.html', requests_list=requests_display_list)

@app.route('/course-request/fulfill/<path:request_id_str>')
@login_required
def fulfill_course_request(request_id_str):
    """Mark a course request as fulfilled using MongoDB"""
    db = get_db()
    if not db: 
        flash('Database error.', 'danger')
        return redirect(url_for('course_requests_list'))
    try:
        request_oid = ObjectId(request_id_str)
    except Exception:
        flash('Invalid request ID format.', 'danger')
        return redirect(url_for('course_requests_list'))

    course_requests_collection = db[COLLECTIONS["course_requests"]]
    result = course_requests_collection.update_one(
        {"_id": request_oid},
        {"$set": {"is_fulfilled": True}}
    )
    if result.modified_count > 0:
        flash('Course request marked as fulfilled!', 'success')
    else:
        flash('Could not mark as fulfilled or already fulfilled.', 'warning')
    return redirect(url_for('course_requests_list'))

@app.route('/course-request/delete/<path:request_id_str>')
@login_required
def delete_course_request(request_id_str):
    """Delete a course request using MongoDB"""
    db = get_db()
    if not db: 
        flash('Database error.', 'danger')
        return redirect(url_for('course_requests_list'))
    try:
        request_oid = ObjectId(request_id_str)
    except Exception:
        flash('Invalid request ID format.', 'danger')
        return redirect(url_for('course_requests_list'))

    course_requests_collection = db[COLLECTIONS["course_requests"]]
    result = course_requests_collection.delete_one({"_id": request_oid})
    if result.deleted_count > 0:
        flash('Course request deleted successfully!', 'success')
    else:
        flash('Course request not found or already deleted.', 'warning')
    return redirect(url_for('course_requests_list'))

if __name__ == '__main__':
    # Consider environment for host and port
    app.run(debug=True, host='0.0.0.0', port=os.getenv('PORT', 5000)) # Use PORT env var for Heroku