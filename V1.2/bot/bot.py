import os
import sys
import asyncio
from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
    Message, CallbackQuery
)
import datetime
import time
from bson import ObjectId # Added for MongoDB

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.config import (
    API_ID, API_HASH, BOT_TOKEN, WELCOME_MESSAGE,
    AUTO_DELETE_SECONDS, AUTO_APPROVE, BOT_PASSWORD, PAYMENT_OPTIONS
)
from database.models import get_db, COLLECTIONS # Removed User, Course, Payment, Log, Category, BotSetting, CourseRequest
from utils.helpers import (
    log_action, save_payment_proof, is_valid_image,
    is_spam, detect_duplicate_payment, format_course_info, # format_course_info is now MongoDB compatible
    shorten_url
)

# Initialize the bot
app = Client(
    "course_delivery_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# User states dictionary
user_states = {}

# Callback data prefixes
CB_COURSE = "course_"
CB_BUY = "buy_"
CB_PAYMENT = "payment_"
CB_ADMIN = "admin_"
CB_BACK = "back"
CB_CANCEL = "cancel"
CB_CATEGORY_SELECT = "cat_select_"       # Select a category
CB_VIEW_CATEGORY_COURSES = "cat_courses_" # View courses in a category
CB_BACK_TO_COURSES = "back_courses"       # Go to full course list view
CB_SHOW_CATEGORIES_MENU = "show_cat_menu" # Go back to category list menu

# State enum
class State:
    IDLE = 0
    AWAITING_PASSWORD = 1
    VIEWING_COURSES = 2
    SELECTING_PAYMENT = 3
    SENDING_PROOF = 4
    ADMIN_LOGIN = 5
    ADMIN_DASHBOARD = 6
    SEARCHING_COURSES = 7
    ENTERING_GIFT_CODE = 8
    AWAITING_COURSE_REQUEST = 9

# Helper functions
async def delete_after_delay(message, delay=AUTO_DELETE_SECONDS):
    """Delete a message after specified delay"""
    if delay > 0:
        await asyncio.sleep(delay)
        try:
            await message.delete()
        except Exception as e:
            print(f"Error deleting message: {e}")

async def get_or_create_user(user_pyrogram_obj: Message.from_user):
    """Get or create a user in the MongoDB database"""
    db = get_db()
    if not db:
        print(f"DB error in get_or_create_user for {user_pyrogram_obj.id}")
        # Depending on bot flow, might need to inform user or raise specific error
        return None 
        
    users_collection = db[COLLECTIONS["users"]]
    # Ensure telegram_id is stored and queried as a string, as user_pyrogram_obj.id is int
    telegram_id_str = str(user_pyrogram_obj.id)
    user_doc = users_collection.find_one({"telegram_id": telegram_id_str})
    
    if not user_doc:
        new_user_data = {
            "telegram_id": telegram_id_str,
            "username": user_pyrogram_obj.username,
            "first_name": user_pyrogram_obj.first_name,
            "last_name": user_pyrogram_obj.last_name,
            "joined_date": datetime.datetime.now(datetime.UTC),
            "is_banned": False,
            "ban_reason": None,
            # Add any other default fields your application expects for a new user
            "purchased_course_ids": [], # Example: list of ObjectIds of purchased courses
            "active_sessions": [] # Example field
        }
        try:
            result = users_collection.insert_one(new_user_data)
            # Fetch the newly created document to include its _id and other defaults
            user_doc = users_collection.find_one({"_id": result.inserted_id})
            # log_action is already refactored for MongoDB
            log_action(
                telegram_id_str,
                "user_joined",
                details=f"New user joined: {user_pyrogram_obj.first_name} {user_pyrogram_obj.last_name} (@{user_pyrogram_obj.username}) ID: {telegram_id_str}"
            )
            print(f"New user {telegram_id_str} created in MongoDB.")
        except Exception as e:
            print(f"Error creating user {telegram_id_str} in MongoDB: {e}")
            # Potentially re-raise or handle based on application needs
            return None
    
    return user_doc # Returns the MongoDB document (a dictionary)

async def get_course_list_markup():
    """Get markup for the course list"""
    db = get_db()
    if not db:
        print("DB error in get_course_list_markup")
        return InlineKeyboardMarkup([[InlineKeyboardButton("Error fetching courses. Please try again later.", callback_data=CB_BACK)]])

    courses_collection = db[COLLECTIONS["courses"]]
    courses = courses_collection.find({"is_active": True}) # Query active courses
    
    keyboard = []
    for course_doc in courses: # course_doc is a MongoDB document (dictionary)
        course_id = str(course_doc["_id"]) # MongoDB _id is an ObjectId, convert to string
        title = course_doc.get("title", "N/A")
        price = course_doc.get("price", 0.0)
        keyboard.append([
            InlineKeyboardButton(
                f"{title} - ₹{price:.2f}", # Assuming price is a float
                callback_data=f"{CB_COURSE}{course_id}"
            )
        ])
    
    # Add back button
    keyboard.append([InlineKeyboardButton("⬅️ Back to Main Menu", callback_data=CB_BACK)])
    
    return InlineKeyboardMarkup(keyboard)

async def get_payment_options_markup(course_id_str: str):
    """Get markup for payment options"""
    keyboard = []
    
    # These PAYMENT_OPTIONS are from config, no DB call needed here for the options themselves
    if PAYMENT_OPTIONS['UPI']:
        keyboard.append([
            InlineKeyboardButton("UPI Payment", callback_data=f"{CB_PAYMENT}upi_{course_id_str}")
        ])
    
    if PAYMENT_OPTIONS['CRYPTO']:
        keyboard.append([
            InlineKeyboardButton("Cryptocurrency", callback_data=f"{CB_PAYMENT}crypto_{course_id_str}")
        ])
    
    if PAYMENT_OPTIONS['PAYPAL']:
        keyboard.append([
            InlineKeyboardButton("PayPal", callback_data=f"{CB_PAYMENT}paypal_{course_id_str}")
        ])
    
    if PAYMENT_OPTIONS['COD']:
        keyboard.append([
            InlineKeyboardButton("Cash on Delivery", callback_data=f"{CB_PAYMENT}cod_{course_id_str}")
        ])
    
    if PAYMENT_OPTIONS['GIFT_CARD']:
        keyboard.append([
            InlineKeyboardButton("Gift Card", callback_data=f"{CB_PAYMENT}gift_{course_id_str}")
        ])
    
    # Add back buttons
    keyboard.append([
        InlineKeyboardButton("⬅️ Back to Course", callback_data=f"{CB_COURSE}{course_id_str}")
    ])
    keyboard.append([
        InlineKeyboardButton("🏠 Main Menu", callback_data=CB_BACK)
    ])
    
    return InlineKeyboardMarkup(keyboard)

async def get_main_menu_markup():
    """Get markup for the main menu. This is static and does not require DB access."""
    keyboard = [
        [KeyboardButton("📚 Browse Courses"), KeyboardButton("🔍 Search Courses")],
        [KeyboardButton("🗂️ Course Categories"), KeyboardButton("👤 My Purchases")],
        [KeyboardButton("✍️ Request Course"), KeyboardButton("📜 DMCA & Policy")],
        [KeyboardButton("❓ Help")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# Command handlers
@app.on_message(filters.command("start"))
async def start_command(client, message):
    """Handle /start command"""
    user = message.from_user
    await get_or_create_user(user)
    
    # Check if the bot has a password set
    if BOT_PASSWORD:
        user_states[user.id] = State.AWAITING_PASSWORD
        welcome_msg = "🔐 This bot is password protected. Please enter the password to continue."
        await message.reply(welcome_msg, quote=True)
    else:
        user_states[user.id] = State.IDLE
        welcome_msg = f"👋 {WELCOME_MESSAGE}\n\nUse the buttons below to navigate."
        reply = await message.reply(
            welcome_msg,
            quote=True,
            reply_markup=await get_main_menu_markup()
        )
    
    log_action(str(user.id), "command_start")

@app.on_message(filters.command("courses"))
async def courses_command(client, message):
    """Handle /courses command"""
    user = message.from_user
    
    # Check if user is authenticated (if password is set)
    if BOT_PASSWORD and user.id not in user_states:
        await start_command(client, message)
        return
    
    user_states[user.id] = State.VIEWING_COURSES
    
    reply = await message.reply(
        "📚 Here are our available courses. Click on any course to view details:",
        quote=True,
        reply_markup=await get_course_list_markup()
    )
    
    log_action(str(user.id), "command_courses")
    asyncio.create_task(delete_after_delay(reply))

@app.on_message(filters.command("help"))
async def help_command(client, message):
    """Handle /help command"""
    user = message.from_user
    
    help_text = (
        "🤖 **Course Delivery Bot Help**\n\n"
        "This bot allows you to browse and purchase courses. After payment verification, "
        "you'll receive access to the course content.\n\n"
        "**Available commands:**\n"
        "/start - Start the bot and view the main menu\n"
        "/courses - Browse available courses\n"
        "/help - Show this help message\n\n"
        "**How to purchase:**\n"
        "1. Browse courses using /courses command\n"
        "2. Select a course to view details\n"
        "3. Click 'Buy Now' and choose a payment method\n"
        "4. Make the payment and send a screenshot as proof\n"
        "5. Wait for approval (instant or manual)\n"
        "6. Receive your course access link\n\n"
        "For any issues, please contact the admin."
    )
    
    reply = await message.reply(
        help_text,
        quote=True
    )
    
    log_action(str(user.id), "command_help")
    asyncio.create_task(delete_after_delay(reply))

# Add a search command
@app.on_message(filters.command("search"))
async def search_command(client, message):
    """Handle /search command"""
    user = message.from_user
    
    # Check if user is authenticated (if password is set)
    if BOT_PASSWORD and user.id not in user_states:
        await start_command(client, message)
        return
    
    await message.reply(
        "🔍 Please enter your search query. You can search by course name or category.",
        quote=True
    )
    
    user_states[user.id] = State.SEARCHING_COURSES
    log_action(str(user.id), "command_search")

# Callback query handlers
@app.on_callback_query()
async def handle_callback(client, callback_query):
    """Handle callback queries from inline buttons"""
    user = callback_query.from_user
    data = callback_query.data
    message = callback_query.message
    
    # Course selection
    if data.startswith(CB_COURSE):
        course_id_str = data[len(CB_COURSE):] # course_id is now a string
        await show_course_details(client, message, user, course_id_str)
    
    # View courses in a category (after selecting a category from category list)
    elif data.startswith(CB_VIEW_CATEGORY_COURSES):
        category_id_str = data[len(CB_VIEW_CATEGORY_COURSES):] # category_id will be a string (ObjectId)
        await show_courses_in_category(client, callback_query, user, category_id_str)
    
    # Go back to category menu
    elif data == CB_SHOW_CATEGORIES_MENU:
        await callback_query.message.delete()
        mock_message_for_reply = Message(chat=callback_query.message.chat, from_user=user, message_id=0)
        await show_categories_menu(client, mock_message_for_reply)

    # Go back to all courses list
    elif data == CB_BACK_TO_COURSES:
        await callback_query.message.delete()
        mock_message_for_reply = Message(chat=callback_query.message.chat, from_user=user, message_id=0)
        await courses_command(client, mock_message_for_reply)
    
    # Buy now
    elif data.startswith(CB_BUY):
        course_id_str = data[len(CB_BUY):] # course_id is now a string
        await show_payment_options(client, message, user, course_id_str)
    
    # Payment method selection
    elif data.startswith(CB_PAYMENT):
        parts = data[len(CB_PAYMENT):].split('_')
        payment_method = parts[0]
        course_id_str = parts[1] # course_id is now a string
        await handle_payment_selection(client, message, user, payment_method, course_id_str)
    
    # Back to main menu
    elif data == CB_BACK:
        # Check if this was a message with an image
        if message.photo:
            # If it's a photo message, we need to delete it and send a new text message
            await message.delete()
            await client.send_message(
                chat_id=message.chat.id,
                text="🏠 Main Menu - Please use the keyboard buttons below to navigate."
            )
        else:
            # Regular text message
            await message.edit_text(
                "🏠 Main Menu - Please use the keyboard buttons below to navigate.",
                reply_markup=None
            )
        user_states[user.id] = State.IDLE
    
    # Cancel operation
    elif data == CB_CANCEL:
        # Check if this was a message with an image
        if message.photo:
            # If it's a photo message, we need to delete it and send a new text message
            await message.delete()
            await client.send_message(
                chat_id=message.chat.id,
                text="❌ Operation cancelled. Use /courses to browse courses or /start to begin again."
            )
        else:
            # Regular text message
            await message.edit_text(
                "❌ Operation cancelled. Use /courses to browse courses or /start to begin again.",
                reply_markup=None
            )
        user_states[user.id] = State.IDLE
    
    # Admin actions
    elif data.startswith(CB_ADMIN):
        # Admin functionality will be implemented separately
        pass
    
    # Acknowledge the callback
    await callback_query.answer()

async def show_course_details(client, message, user, course_id_str: str):
    """Show course details and buy option"""
    db = get_db()
    if not db:
        # Handle DB error appropriately
        await message.edit_text("Error connecting to database. Please try again later.")
        return

    courses_collection = db[COLLECTIONS["courses"]]
    try:
        course_doc = courses_collection.find_one({"_id": ObjectId(course_id_str), "is_active": True})
    except Exception as e: # Handles invalid ObjectId format
        print(f"Error finding course with ID {course_id_str}: {e}")
        course_doc = None
    
    if not course_doc:
        reply_markup = await get_course_list_markup() # Get the general course list markup
        if message.photo:
            await message.delete()
            await client.send_message(
                chat_id=message.chat.id,
                text="❌ Course not found or no longer available.",
                reply_markup=reply_markup
            )
        else:
            await message.edit_text(
                "❌ Course not found or no longer available.",
                reply_markup=reply_markup
            )
        return
    
    # Create keyboard with Buy Now button and other options
    keyboard = []
    is_free = course_doc.get("is_free", False)
    if is_free:
        keyboard.append([InlineKeyboardButton("🎁 Get Now for FREE", callback_data=f"{CB_BUY}{course_id_str}")])
    else:
        keyboard.append([InlineKeyboardButton("💲 Buy Now", callback_data=f"{CB_BUY}{course_id_str}")])
    
    # TODO: Consider making admin contact configurable
    keyboard.append([InlineKeyboardButton("👨‍💼 Buy Directly from Admin", url=f"https://t.me/ANONYMOUS_AMIT")])
    
    # Add Demo Video button if link exists
    demo_video_link = course_doc.get("demo_video_link")
    if demo_video_link:
        keyboard.append([InlineKeyboardButton("🎬 DEMO VIDEOS ✅", url=demo_video_link)])

    # Add back button
    # CB_BACK_TO_COURSES will take them to the full course list, or CB_SHOW_CATEGORIES_MENU if they came from a category view.
    # For simplicity now, always going back to full course list via CB_BACK_TO_COURSES if we used get_course_list_markup.
    # If they came from a category, the CB_BACK would ideally go to that category. This requires more state tracking or smarter CB_BACK.
    # For now, let's use CB_BACK_TO_COURSES for a consistent back to list behavior from course details.
    keyboard.append([InlineKeyboardButton("⬅️ Back to Courses", callback_data=CB_BACK_TO_COURSES)]) 
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Format course details using the already MongoDB-compatible helper
    course_text = format_course_info(course_doc)
    
    # Image handling logic (mostly unchanged, but ensure image_link is fetched from course_doc)
    image_link = course_doc.get("image_link")

    if image_link and not message.photo: # If there's an image link and current message is not a photo
        try:
            chat_id = message.chat.id
            try:
                await message.delete()
            except Exception as e:
                print(f"Error deleting message: {e}")
            
            if "localhost" in image_link or "127.0.0.1" in image_link or "192.168" in image_link:
                await client.send_message(
                    chat_id=chat_id,
                    text=f"{course_text}\n\n_Note: Course image available on website_",
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                try:
                    await client.send_photo(
                        chat_id=chat_id,
                        photo=image_link,
                        caption=course_text,
                        reply_markup=reply_markup,
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception as e:
                    print(f"Error sending photo, falling back to text: {e}")
                    await client.send_message(
                        chat_id=chat_id,
                        text=f"{course_text}\n\n_Note: Course image could not be displayed._",
                        reply_markup=reply_markup,
                        parse_mode=ParseMode.MARKDOWN
                    )
        except Exception as e:
            print(f"Error in show_course_details (image sending): {e}")
            # Fallback to editing the original message if sending new one fails
            try:
                await message.edit_text(
                    course_text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e2:
                print(f"Secondary error in show_course_details (editing after fail): {e2}")
    else: # If no image link, or message is already a photo, just edit the text/caption
        try:
            if message.photo: # If current message is a photo, edit its caption
                 await message.edit_caption(
                    caption=course_text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                 )
            else: # If current message is text, edit its text
                await message.edit_text(
                    course_text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
        except Exception as e:
            # If editing fails, it might be because the content is identical or other Telegram API issue.
            print(f"Error updating message (edit_text/edit_caption): {e}")
            # As a last resort, if the original message was a photo and we are trying to edit text, 
            # it won't work. Send a new message.
            if message.photo and not image_link:
                 try:
                    await client.send_message(
                        chat_id=message.chat.id,
                        text=course_text,
                        reply_markup=reply_markup,
                        parse_mode=ParseMode.MARKDOWN
                    )
                 except Exception as e3:
                    print(f"Error sending new text message after edit caption failed: {e3}")

    user_states[user.id] = State.VIEWING_COURSES # User is viewing a course
    log_action(str(user.id), "view_course", details=f"Viewed course: {course_doc.get('title', 'N/A')}")

async def show_payment_options(client, message, user, course_id_str: str):
    """Show payment options for a course"""
    db = get_db()
    if not db:
        await message.edit_text("Error connecting to database. Please try again later.")
        return

    courses_collection = db[COLLECTIONS["courses"]]
    try:
        course_doc = courses_collection.find_one({"_id": ObjectId(course_id_str), "is_active": True})
    except Exception as e: # Handles invalid ObjectId format
        print(f"Error finding course for payment options with ID {course_id_str}: {e}")
        course_doc = None

    if not course_doc:
        reply_markup = await get_course_list_markup()
        if message.photo:
            await message.delete()
            await client.send_message(
                chat_id=message.chat.id,
                text="❌ Course not found or no longer available.",
                reply_markup=reply_markup
            )
        else:
            await message.edit_text(
                "❌ Course not found or no longer available.",
                reply_markup=reply_markup
            )
        return
    
    is_free = course_doc.get("is_free", False)
    if is_free:
        await send_course_link(client, message, user, course_doc, is_free_course=True)
        log_action(str(user.id), "get_free_course", details=f"Accessed free course: {course_doc.get('title', 'N/A')}")
        user_states[user.id] = State.IDLE 
        return

    course_payment_options_str = course_doc.get("payment_options") 
    payment_options_list = []
    if course_payment_options_str:
        payment_options_list = [opt.strip() for opt in course_payment_options_str.split(',')]
    
    active_payment_methods = []
    if not payment_options_list:
        if PAYMENT_OPTIONS.get('UPI'): active_payment_methods.append('upi')
        if PAYMENT_OPTIONS.get('CRYPTO'): active_payment_methods.append('crypto')
        if PAYMENT_OPTIONS.get('PAYPAL'): active_payment_methods.append('paypal')
        if PAYMENT_OPTIONS.get('COD'): active_payment_methods.append('cod') # Assuming 'COD' key exists if enabled
        if PAYMENT_OPTIONS.get('GIFT_CARD'): active_payment_methods.append('gift') # Assuming 'GIFT_CARD' key exists
    else:
        active_payment_methods = payment_options_list
    
    keyboard = []
    if 'upi' in active_payment_methods and PAYMENT_OPTIONS.get('UPI'):
        keyboard.append([InlineKeyboardButton("UPI Payment", callback_data=f"{CB_PAYMENT}upi_{course_id_str}")])
    if 'crypto' in active_payment_methods and PAYMENT_OPTIONS.get('CRYPTO'):
        keyboard.append([InlineKeyboardButton("Cryptocurrency", callback_data=f"{CB_PAYMENT}crypto_{course_id_str}")])
    if 'paypal' in active_payment_methods and PAYMENT_OPTIONS.get('PAYPAL'):
        keyboard.append([InlineKeyboardButton("PayPal", callback_data=f"{CB_PAYMENT}paypal_{course_id_str}")])
    if 'cod' in active_payment_methods: # COD might be enabled without a specific value in PAYMENT_OPTIONS
        keyboard.append([InlineKeyboardButton("Cash on Delivery", callback_data=f"{CB_PAYMENT}cod_{course_id_str}")])
    if 'gift' in active_payment_methods: # Gift card might be enabled without a specific value
        keyboard.append([InlineKeyboardButton("Gift Card", callback_data=f"{CB_PAYMENT}gift_{course_id_str}")])
    
    keyboard.append([InlineKeyboardButton("👨‍💼 Buy Directly from Admin ", url="https://t.me/ANONYMOUS_AMIT")])
    keyboard.append([InlineKeyboardButton("⬅️ Back to Course", callback_data=f"{CB_COURSE}{course_id_str}")])
    keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data=CB_BACK)])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    course_title = course_doc.get("title", "N/A")
    course_price = course_doc.get("price", 0.0)
    payment_text = (
        f"💰 **Payment for: {course_title}**\n\n"
        f"💵 Amount: ₹{course_price:.2f}\n\n"
        f"Please select your preferred payment method:\n\n"
        f"_Note: For faster processing, you can buy directly from our admin._"
    )
    
    if message.photo:
        await message.delete()
        await client.send_message(
            chat_id=message.chat.id,
            text=payment_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await message.edit_text(
            payment_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    user_states[user.id] = State.SELECTING_PAYMENT
    log_action(str(user.id), "select_payment", details=f"Selected payment for: {course_title}")

async def handle_payment_selection(client, message, user, payment_method, course_id_str: str):
    """Handle payment method selection"""
    db = get_db()
    if not db:
        await message.edit_text("Error connecting to database. Please try again later.")
        return

    courses_collection = db[COLLECTIONS["courses"]]
    try:
        course_doc = courses_collection.find_one({"_id": ObjectId(course_id_str), "is_active": True})
    except Exception as e: # Handles invalid ObjectId format
        print(f"Error finding course for payment selection with ID {course_id_str}: {e}")
        course_doc = None

    if not course_doc:
        # It might be better to send a new message if the original was a photo or complex.
        await message.edit_text("❌ Course not found or no longer available.") 
        return

    course_title = course_doc.get("title", "N/A")
    course_price = course_doc.get("price", 0.0)
    payment_details = ""
    qr_image_path = None # This will be a path to a locally stored QR image if used
    qr_image_field_in_db = course_doc.get("qr_code_image") # Filename of QR from DB

    if payment_method == "upi":
        upi_id = PAYMENT_OPTIONS.get('UPI')
        if not upi_id:
            await message.edit_text("UPI payment is currently unavailable. Please select another method.")
            return
        payment_details = f"UPI ID: {upi_id}"
        if qr_image_field_in_db: # e.g., "course_upi_qr.png"
            # Construct path assuming UPLOAD_FOLDER/qr_codes/<filename>
            # This needs to align with how admin panel saves/names these QRs.
            # For now, let's assume a simple structure relative to a known QR folder.
            # IMPORTANT: Ensure this path is correct for your deployment.
            qr_image_path = os.path.join("uploads", "qr_codes", qr_image_field_in_db) 
            if not os.path.exists(qr_image_path):
                # Fallback or secondary check if not in primary path
                alt_qr_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads", "qr_codes", qr_image_field_in_db)
                if os.path.exists(alt_qr_path):
                    qr_image_path = alt_qr_path
                else:
                    print(f"QR Code image not found: {qr_image_field_in_db} at {qr_image_path} or {alt_qr_path}")
                    qr_image_path = None 

    elif payment_method == "crypto":
        crypto_address = PAYMENT_OPTIONS.get('CRYPTO')
        if not crypto_address:
            await message.edit_text("Crypto payment is currently unavailable. Please select another method.")
            return
        payment_details = f"Crypto Address: {crypto_address}"
    elif payment_method == "paypal":
        paypal_info = PAYMENT_OPTIONS.get('PAYPAL')
        if not paypal_info:
            await message.edit_text("PayPal payment is currently unavailable. Please select another method.")
            return
        payment_details = f"PayPal: {paypal_info}"
    elif payment_method == "cod":
        # COD might not need details from PAYMENT_OPTIONS if it's just an instruction
        payment_details = f"Cash on Delivery: Please be ready with ₹{course_price:.2f}. Our representative will contact you for delivery details."
    elif payment_method == "gift":
        gift_card_text = (
            f"💳 **Gift Card Redemption**\n\n"
            f"You've selected to pay with a gift card for: **{course_title}**\n\n"
            f"💰 **Amount:** ₹{course_price:.2f}\n\n"
            f"Please enter your gift card code. We accept Amazon, Google Play, and other popular gift cards.\n\n"
            f"_Note: Gift card redemption is subject to manual verification and may take up to 24 hours._"
        )
        if message.photo:
            await message.delete()
            await client.send_message(
                chat_id=message.chat.id,
                text=gift_card_text,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=CB_CANCEL)]]),
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await message.edit_text(
                gift_card_text,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=CB_CANCEL)]]),
                parse_mode=ParseMode.MARKDOWN
            )
        
        user_states[user.id] = State.ENTERING_GIFT_CODE
        user_states[f"{user.id}_course"] = course_id_str # Store as string
        user_states[f"{user.id}_payment_method"] = payment_method
        log_action(str(user.id), "gift_card_selected", details=f"Selected gift card for course: {course_title}")
        return
    
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data=CB_CANCEL)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    user_states[user.id] = State.SENDING_PROOF
    user_states[f"{user.id}_course"] = course_id_str # Store as string
    user_states[f"{user.id}_payment_method"] = payment_method
    
    payment_instructions = (
        f"💳 **Payment Instructions**\n\n"
        f"You've selected: **{payment_method.upper()}** for **{course_title}**\n\n"
        f"📝 **Details:**\n{payment_details}\n\n"
        f"💰 **Amount:** ₹{course_price:.2f}\n\n"
        f"Please make the payment and send a screenshot as proof. "
        f"Once verified, you'll receive access to the course."
    )
    
    # Delete previous message (e.g., payment options keyboard) and send new ones
    if message.photo: # If previous message was a photo (unlikely here, but good practice)
        await message.delete()
        current_chat_id = message.chat.id # Save chat_id before message is deleted
    else:
        try:
            current_chat_id = message.chat.id
            await message.delete() # Delete the message with payment options
        except Exception as e:
            print(f"Error deleting message before sending payment instructions: {e}")
            current_chat_id = message.chat.id # Fallback to original chat_id

    # Send QR code first if available (for UPI)
    if qr_image_path:
        try:
            await client.send_photo(
                chat_id=current_chat_id,
                photo=qr_image_path,
                caption=f"Scan this QR Code for UPI Payment (₹{course_price:.2f}) for {course_title}"
            )
        except Exception as e:
            print(f"Error sending QR photo: {e}. QR path: {qr_image_path}")
            payment_instructions += f"\n\n(QR code image for ₹{course_price:.2f} was intended here but failed to send)"

    await client.send_message(
        chat_id=current_chat_id,
        text=payment_instructions,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
    
    log_action(str(user.id), "payment_method_selected", details=f"Selected {payment_method} for course: {course_title}")

async def handle_gift_code(client, message, user, gift_code: str):
    """Handle gift card code submission and save to MongoDB"""
    # Delete the message with the gift code for security (already present)
    try:
        await message.delete()
    except Exception as e:
        print(f"Error deleting gift code message: {e}")
    
    course_id_str = user_states.get(f"{user.id}_course")
    if not course_id_str:
        await client.send_message(
            chat_id=message.chat.id,
            text="❌ Error processing gift card: Course information missing. Please try again or contact support.",
            reply_markup=await get_main_menu_markup() # Main menu markup is static
        )
        user_states[user.id] = State.IDLE
        return

    db = get_db()
    if not db:
        await client.send_message(message.chat.id, "Database error. Please try again later.")
        user_states[user.id] = State.IDLE
        return

    courses_collection = db[COLLECTIONS["courses"]]
    payments_collection = db[COLLECTIONS["payments"]]

    try:
        course_doc = courses_collection.find_one({"_id": ObjectId(course_id_str)})
    except Exception as e:
        print(f"Error finding course {course_id_str} for gift code: {e}")
        course_doc = None

    if not course_doc:
        await client.send_message(
            chat_id=message.chat.id,
            text="❌ Course not found or no longer available for gift card redemption.",
            reply_markup=await get_main_menu_markup()
        )
        user_states[user.id] = State.IDLE
        return

    # Get or create user (already MongoDB compatible)
    db_user_doc = await get_or_create_user(user) # user is a Pyrogram User object
    if not db_user_doc:
        await client.send_message(message.chat.id, "Could not retrieve user information. Please try again.")
        user_states[user.id] = State.IDLE
        return

    course_title = course_doc.get("title", "N/A")
    course_price = course_doc.get("price", 0.0)

    payment_document = {
        "user_id": db_user_doc["_id"],  # Store ObjectId of the user
        "telegram_user_id": db_user_doc["telegram_id"], # For easier lookup if needed
        "course_id": course_doc["_id"], # Store ObjectId of the course
        "course_title": course_title, # Denormalize for convenience
        "payment_method": "gift",
        "payment_proof": None,  # No screenshot for gift cards initially
        "amount": course_price,
        "status": 'pending', # Gift cards usually require manual verification
        "submission_date": datetime.datetime.now(datetime.UTC),
        "ip_address": None,  # Not available from Telegram
        "details": f"Gift Card Code: {gift_code}" # Store full gift code for admin review
    }
    
    try:
        result = payments_collection.insert_one(payment_document)
        payment_id = result.inserted_id
        print(f"Gift card payment {payment_id} for user {db_user_doc['telegram_id']} and course {course_title} submitted.")

        await client.send_message(
            chat_id=message.chat.id,
            text=f"✅ Your gift card code has been submitted successfully!\n\n"
                 f"📝 **Details:**\n"
                 f"- Course: {course_title}\n"
                 f"- Amount: ₹{course_price:.2f}\n"
                 f"- Gift Card Code: {gift_code} (Hidden for your privacy in this message)\n\n"
                 f"⏳ Your code is being verified by our admin team. This process may take up to 24 hours.\n\n"
                 f"You'll be notified once your payment is approved.",
            reply_markup=await get_main_menu_markup(),
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        print(f"Error inserting gift card payment into MongoDB: {e}")
        await client.send_message(message.chat.id, "An error occurred while submitting your gift card. Please contact support.")
    
    # Reset user state
    user_states[user.id] = State.IDLE
    if f"{user.id}_course" in user_states: del user_states[f"{user.id}_course"]
    if f"{user.id}_payment_method" in user_states: del user_states[f"{user.id}_payment_method"]
    
    log_action(
        str(user.id),
        "gift_card_submitted",
        details=f"Submitted gift card for course: {course_title}" # Avoid logging full code here
    )

# Handle text messages (for password and other text inputs)
@app.on_message(filters.text)
async def handle_text(client, message):
    """Handle text messages"""
    user = message.from_user
    text = message.text
    
    # Skip command messages
    if text.startswith('/'):
        return
    
    # Check if awaiting password
    if user.id in user_states and user_states[user.id] == State.AWAITING_PASSWORD:
        if text == BOT_PASSWORD:
            user_states[user.id] = State.IDLE
            welcome_msg = f"✅ Password correct!\n\n👋 {WELCOME_MESSAGE}\n\nUse the buttons below to navigate."
            await message.reply(
                welcome_msg,
                quote=True,
                reply_markup=await get_main_menu_markup()
            )
            log_action(str(user.id), "password_correct")
        else:
            await message.reply(
                "❌ Incorrect password. Please try again or contact the admin.",
                quote=True
            )
            log_action(str(user.id), "password_incorrect")
        
        # Delete the message containing the password attempt
        await message.delete()
        return
    
    # Check if user is searching for courses
    elif user.id in user_states and user_states[user.id] == State.SEARCHING_COURSES:
        await handle_course_search(client, message, user, text)
        return
    
    # Check if user is entering gift code
    elif user.id in user_states and user_states[user.id] == State.ENTERING_GIFT_CODE:
        await handle_gift_code(client, message, user, text)
        return
    
    # Check if user is awaiting course request
    elif user.id in user_states and user_states[user.id] == State.AWAITING_COURSE_REQUEST:
        await save_course_request(client, message, user, text)
        return
    
    # Handle keyboard button presses
    if text == "📚 Browse Courses":
        await courses_command(client, message)
    elif text == "🔍 Search Courses":
        await search_command(client, message)
    elif text == "🗂️ Course Categories":
        await show_categories_menu(client, message)
    elif text == "📜 DMCA & Policy":
        await show_dmca_policy(client, message)
    elif text == "✍️ Request Course":
        await handle_request_course_button(client, message)
    elif text == "❓ Help":
        await help_command(client, message)
    elif text == "👤 My Purchases":
        await show_purchases(client, message)
    else:
        # Handle other text inputs
        if is_spam(text):
            log_action(str(user.id), "spam_detected", details=f"Spam message: {text[:50]}...")
            await message.reply(
                "⚠️ Your message has been flagged as potential spam and will not be processed.",
                quote=True
            )
            return
        
        await message.reply(
            "I don't understand this command. Please use the buttons or /help for assistance.",
            quote=True
        )

async def show_purchases(client, message):
    """Show user's purchases from MongoDB."""
    user_pyrogram_obj = message.from_user
    db = get_db()
    if not db:
        await message.reply("Database error. Please try again later.", quote=True)
        return

    # Get user document (already MongoDB compatible)
    user_doc = await get_or_create_user(user_pyrogram_obj)
    if not user_doc:
        await message.reply("Could not retrieve your user information. Please try again.", quote=True)
        return

    payments_collection = db[COLLECTIONS["payments"]]
    courses_collection = db[COLLECTIONS["courses"]]

    try:
        # Get approved payments for this user, sorted by approval_date descending perhaps
        approved_payments_cursor = payments_collection.find({
            "user_id": user_doc["_id"], # Query by user's ObjectId
            "status": "approved"
        }).sort("approval_date", -1) # -1 for descending
        
        approved_payments = list(approved_payments_cursor)
    except Exception as e:
        print(f"Error fetching purchases for user {user_doc['telegram_id']}: {e}")
        await message.reply("Could not retrieve your purchase history. Please try again.", quote=True)
        return

    if not approved_payments:
        await message.reply(
            "You haven't purchased any courses yet. Use /courses or the '📚 Browse Courses' button to see available courses.",
            quote=True,
            reply_markup=await get_main_menu_markup() # Static markup
        )
        return
    
    purchases_text = "🛒 **Your Purchases:**\n\n"
    course_details_cache = {} # Cache course details to avoid multiple DB hits for the same course if purchased multiple times

    for i, payment_doc in enumerate(approved_payments, 1):
        course_id = payment_doc.get("course_id")
        course_doc = None

        if course_id in course_details_cache:
            course_doc = course_details_cache[course_id]
        elif course_id:
            try:
                course_doc = courses_collection.find_one({"_id": course_id})
                if course_doc:
                    course_details_cache[course_id] = course_doc
            except Exception as e:
                print(f"Error fetching course details for course ID {course_id} in purchases: {e}")
        
        if course_doc:
            course_title = course_doc.get("title", "N/A")
            course_file_link = course_doc.get("file_link", "#") # Default to # if no link
            short_link = shorten_url(course_file_link) # shorten_url helper is generic
            
            amount_paid = payment_doc.get("amount", 0.0)
            approval_date_dt = payment_doc.get("approval_date")
            approval_date_str = approval_date_dt.strftime('%Y-%m-%d') if approval_date_dt else "N/A"
            
            purchases_text += (
                f"{i}. **{course_title}**\n"
                f"   💰 Price Paid: ₹{amount_paid:.2f}\n"
                f"   📅 Purchased: {approval_date_str}\n"
                f"   🔗 [Access Course]({short_link})\n\n"
            )
        else:
            # Fallback if course details couldn't be fetched for some reason
            purchases_text += (
                f"{i}. **Course ID: {str(course_id)}** (Details unavailable)\n"
                f"   📅 Purchased: {payment_doc.get('approval_date', 'N/A').strftime('%Y-%m-%d') if payment_doc.get('approval_date') else 'N/A'}\n\n"
            )

    # Telegram message length limit is 4096 characters. Consider pagination for many purchases.
    if len(purchases_text) > 4000: # Simple check, can be more precise
        # For now, just truncate. Ideally, implement pagination.
        purchases_text = purchases_text[:4000] + "\n\n... (list truncated due to length)"
        
    await message.reply(
        purchases_text,
        quote=True,
        disable_web_page_preview=True,
        parse_mode=ParseMode.MARKDOWN
    )
    
    log_action(str(user_doc["telegram_id"]), "view_purchases")

# Handle photo messages (payment proofs)
@app.on_message(filters.photo)
async def handle_photo(client, message):
    """Handle photo uploads (payment proofs) with MongoDB backend."""
    user_pyrogram_obj = message.from_user
    
    if (user_pyrogram_obj.id not in user_states or
            user_states[user_pyrogram_obj.id] != State.SENDING_PROOF or
            f"{user_pyrogram_obj.id}_course" not in user_states):
        await message.reply(
            "❓ I wasn't expecting a photo. If you're trying to submit a payment proof, "
            "please select a course and payment method first.",
            quote=True
        )
        return
    
    photo_file_id = message.photo.file_id
    try:
        file_bytes_io = await client.download_media(photo_file_id, in_memory=True)
        file_bytes = file_bytes_io.getvalue()
    except Exception as e:
        print(f"Error downloading photo: {e}")
        await message.reply("Error processing photo. Please try sending it again.", quote=True)
        return
    
    if not is_valid_image(file_bytes): # is_valid_image helper expects bytes
        await message.reply("❌ The file you sent doesn't appear to be a valid image. Please try again.", quote=True)
        return
    
    # detect_duplicate_payment helper might need its own MongoDB integration if it checks DB hashes
    if detect_duplicate_payment(file_bytes, str(user_pyrogram_obj.id)):
        await message.reply(
            "⚠️ This payment proof appears to be a duplicate. If this is a mistake, please contact the admin.",
            quote=True
        )
        log_action(str(user_pyrogram_obj.id), "duplicate_payment_detected")
        return
    
    course_id_str = user_states[f"{user_pyrogram_obj.id}_course"]
    payment_method = user_states[f"{user_pyrogram_obj.id}_payment_method"]
    
    db = get_db()
    if not db:
        await message.reply("Database error. Could not process payment. Please try again later.", quote=True)
        return

    courses_collection = db[COLLECTIONS["courses"]]
    payments_collection = db[COLLECTIONS["payments"]]

    try:
        course_doc = courses_collection.find_one({"_id": ObjectId(course_id_str)})
    except Exception as e:
        print(f"Error finding course {course_id_str} for payment proof: {e}")
        course_doc = None

    if not course_doc:
        await message.reply("❌ Course not found for this payment. Please try again or contact support.", quote=True)
        return

    user_doc = await get_or_create_user(user_pyrogram_obj) # Ensures user exists in DB
    if not user_doc:
        await message.reply("Could not retrieve your user information. Please try again.", quote=True)
        return

    filename = save_payment_proof(str(user_pyrogram_obj.id), file_bytes) # save_payment_proof takes bytes
    if not filename:
        await message.reply("❌ Error saving payment proof file. Please try again or contact admin.", quote=True)
        return
    
    course_title = course_doc.get("title", "N/A")
    course_price = course_doc.get("price", 0.0)

    payment_document = {
        "user_id": user_doc["_id"],
        "telegram_user_id": user_doc["telegram_id"],
        "course_id": course_doc["_id"],
        "course_title": course_title,
        "payment_method": payment_method,
        "payment_proof_filename": filename, # Store filename of the proof
        "amount": course_price,
        "status": 'pending',
        "submission_date": datetime.datetime.now(datetime.UTC),
        "ip_address": None 
    }

    try:
        insert_result = payments_collection.insert_one(payment_document)
        payment_id = insert_result.inserted_id
    except Exception as e:
        print(f"Error inserting payment document into MongoDB: {e}")
        await message.reply("An error occurred while recording your payment. Please contact support.", quote=True)
        # Clean up states if DB insert fails
        user_states.pop(f"{user_pyrogram_obj.id}_course", None)
        user_states.pop(f"{user_pyrogram_obj.id}_payment_method", None)
        user_states[user_pyrogram_obj.id] = State.IDLE
        return

    if AUTO_APPROVE:
        try:
            payments_collection.update_one(
                {"_id": payment_id},
                {"$set": {"status": "approved", "approval_date": datetime.datetime.now(datetime.UTC)}}
            )
            # Fetch the updated payment doc or pass relevant fields to send_course_link
            # For simplicity, we pass the course_doc which has title and link
            await send_course_link(client, message, user_pyrogram_obj, course_doc) # send_course_link needs course_doc
            log_action(str(user_doc["telegram_id"]), "payment_auto_approved", details=f"Auto-approved payment for: {course_title}")
        except Exception as e:
            print(f"Error auto-approving payment {payment_id}: {e}")
            # If auto-approval fails, it remains pending. Inform user.
            await message.reply(
                "✅ Your payment proof has been submitted but auto-approval failed. It is pending manual verification. "
                "You'll be notified once it's approved.",
                quote=True
            )
            log_action(str(user_doc["telegram_id"]), "payment_submitted_auto_approve_failed", details=f"Submitted payment for: {course_title}")
    else:
        await message.reply(
            "✅ Your payment proof has been submitted and is pending verification by an admin. "
            "You'll be notified once it's approved.",
            quote=True
        )
        log_action(str(user_doc["telegram_id"]), "payment_submitted_manual_verification", details=f"Submitted payment for: {course_title}")
    
    user_states.pop(f"{user_pyrogram_obj.id}_course", None)
    user_states.pop(f"{user_pyrogram_obj.id}_payment_method", None)
    user_states[user_pyrogram_obj.id] = State.IDLE

async def send_course_link(client, message, user, course_doc, is_free_course=False):
    """Send course link to the user. Expects course_doc as MongoDB document."""
    file_link = course_doc.get("file_link", "#")
    course_title = course_doc.get("title", "N/A")
    short_link = shorten_url(file_link)
    
    if is_free_course:
        course_access_message = (
            f"🎉 **Here is your free course!**\n\n"
            f"You now have access to: **{course_title}**\n\n"
            f"🔗 **Access your course here:**\n"
            f"[Course Link]({short_link})\n\n"
            f"Enjoy your learning!"
        )
    else:
        course_access_message = (
            f"🎉 **Payment Approved!**\n\n"
            f"You now have access to: **{course_title}**\n\n"
            f"🔗 **Access your course here:**\n"
            f"[Course Link]({short_link})\n\n"
            f"Thank you for your purchase! If you have any questions or issues, please contact support."
        )
    
    # Reply to the original message that triggered this flow (e.g., the photo submission message)
    await message.reply(
        course_access_message,
        quote=True,
        disable_web_page_preview=True,
        parse_mode=ParseMode.MARKDOWN # Ensure markdown is parsed for links
    )

async def handle_course_search(client, message, user, query: str):
    """Handle course search by name or category using MongoDB"""
    db = get_db()
    if not db:
        await message.reply("Database error. Please try again later.", quote=True)
        user_states[user.id] = State.IDLE
        return

    courses_collection = db[COLLECTIONS["courses"]]
    categories_collection = db[COLLECTIONS["categories"]]

    # Build a regex query for case-insensitive search
    # The 'i' option makes it case-insensitive
    regex_query = {"$regex": query, "$options": "i"}

    # Find category IDs that match the query to search courses by category name
    matching_category_ids = []
    try:
        # Search for categories where the name matches the query
        matching_categories = categories_collection.find({"name": regex_query}, {"_id": 1})
        matching_category_ids = [cat["_id"] for cat in matching_categories]
    except Exception as e:
        print(f"Error searching categories for query '{query}': {e}")

    # Build the MongoDB query for courses
    # Search in course title OR if course's category_id is in matching_category_ids
    mongo_db_query = {
        "is_active": True,
        "$or": [
            {"title": regex_query},
        ]
    }
    if matching_category_ids:
        mongo_db_query["$or"].append({"category_id": {"$in": matching_category_ids}})

    try:
        # Execute the query, sorting by title perhaps, or add other sorting as needed
        # .limit(20) # Optionally limit results to prevent overly long messages
        found_courses = list(courses_collection.find(mongo_db_query).sort("title", 1))
    except Exception as e:
        print(f"Error searching courses with query '{query}': {e}")
        await message.reply("An error occurred during search. Please try again.", quote=True)
        user_states[user.id] = State.IDLE
        return

    if not found_courses:
        await message.reply(
            "❌ No courses found matching your search. Please try a different query or browse all courses.\n\nAlternatively, you can find a list of all available courses here: @Available_course_list", # Consider making this configurable
            quote=True,
            reply_markup=await get_main_menu_markup(), # Static markup
            disable_web_page_preview=True
        )
        user_states[user.id] = State.IDLE
        return

    keyboard = []
    for course_doc in found_courses:
        course_id_str = str(course_doc["_id"])
        title = course_doc.get("title", "N/A")
        price = course_doc.get("price", 0.0)
        price_display = f"₹{price:.2f}" if not course_doc.get("is_free") else "FREE"
        keyboard.append([
            InlineKeyboardButton(
                f"{title} - {price_display}",
                callback_data=f"{CB_COURSE}{course_id_str}"
            )
        ])

    keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data=CB_BACK)])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await message.reply(
        f"🔍 Search results for '{query}':\n\nFound {len(found_courses)} courses. Tap on a course to view details:",
        quote=True,
        reply_markup=reply_markup
    )

    user_states[user.id] = State.VIEWING_COURSES # Set state to viewing courses after search
    log_action(str(user.id), "search_courses", details=f"Searched for: {query}, Found: {len(found_courses)} courses")

async def show_categories_menu(client, message: Message):
    """Display a menu of course categories from MongoDB."""
    user = message.from_user # Not strictly needed for DB query, but good for context
    db = get_db()
    if not db:
        await message.reply("Database error. Please try again later.", quote=True)
        return

    categories_collection = db[COLLECTIONS["categories"]]
    courses_collection = db[COLLECTIONS["courses"]]

    # Fetch all categories, ordered by name
    # We could also use an aggregation pipeline to get counts directly, but this is simpler for now.
    try:
        all_categories = list(categories_collection.find().sort("name", 1))
    except Exception as e:
        print(f"Error fetching categories: {e}")
        await message.reply("Could not load categories. Please try again.", quote=True)
        return

    if not all_categories:
        await message.reply(
            "😔 No course categories are currently available. Please check back later or browse all courses.",
            quote=True,
            reply_markup=await get_main_menu_markup() # Static markup
        )
        return

    keyboard = []
    for cat_doc in all_categories:
        category_id = cat_doc["_id"] # This is an ObjectId
        category_name = cat_doc.get("name", "Unnamed Category")
        
        # Count active courses for this category
        try:
            active_courses_count = courses_collection.count_documents({
                "category_id": category_id, 
                "is_active": True
            })
        except Exception as e:
            print(f"Error counting courses for category {category_name}: {e}")
            active_courses_count = 0 # Assume 0 if error
            
        if active_courses_count > 0:
            keyboard.append([InlineKeyboardButton(
                f"{category_name} ({active_courses_count})", 
                callback_data=f"{CB_VIEW_CATEGORY_COURSES}{str(category_id)}" # Pass category_id as string
            )])

    if not keyboard: # If all categories ended up having 0 active courses
        await message.reply(
            "😔 No courses are currently available in any category. Please check back later or browse all courses.",
            quote=True,
            reply_markup=await get_main_menu_markup()
        )
        return

    keyboard.append([InlineKeyboardButton("📚 All Courses", callback_data=CB_BACK_TO_COURSES)])
    keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data=CB_BACK)])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await message.reply(
        "🗂️ **Course Categories**\n\nSelect a category to view its courses:",
        quote=True,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
    # user_states[user.id] = State.VIEWING_CATEGORIES 
    log_action(str(user.id), "view_categories_menu")

async def show_courses_in_category(client, callback_query: CallbackQuery, user, category_id_str: str):
    """Display courses within a selected category using MongoDB."""
    message = callback_query.message 
    db = get_db()
    if not db:
        await message.edit_text("Database error. Please try again later.", reply_markup=await get_main_menu_markup())
        return

    categories_collection = db[COLLECTIONS["categories"]]
    courses_collection = db[COLLECTIONS["courses"]]
    category_obj_id = None
    try:
        category_obj_id = ObjectId(category_id_str)
        category_doc = categories_collection.find_one({"_id": category_obj_id})
    except Exception as e: # Handles invalid ObjectId format or other DB errors
        print(f"Error finding category with ID {category_id_str}: {e}")
        category_doc = None
    
    if not category_doc:
        await message.edit_text("❌ Category not found.", reply_markup=await get_main_menu_markup())
        return

    category_name = category_doc.get("name", "Unnamed Category")

    try:
        # Find active courses in this category, ordered by title
        courses_cursor = courses_collection.find({
            "category_id": category_obj_id, 
            "is_active": True
        }).sort("title", 1)
        courses_in_category = list(courses_cursor)
    except Exception as e:
        print(f"Error fetching courses for category {category_name}: {e}")
        await message.edit_text(f"Error loading courses for {category_name}. Please try again.")
        return

    if not courses_in_category:
        await message.edit_text(
            f"😔 No active courses found in the category: **{category_name}**.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back to Categories", callback_data=CB_SHOW_CATEGORIES_MENU)],
                [InlineKeyboardButton("🏠 Main Menu", callback_data=CB_BACK)]
            ]),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    keyboard = []
    for course_doc in courses_in_category:
        course_id = str(course_doc["_id"])
        title = course_doc.get("title", "N/A")
        price = course_doc.get("price", 0.0)
        is_free = course_doc.get("is_free", False)
        price_display = "FREE" if is_free else f"₹{price:.2f}"
        keyboard.append([
            InlineKeyboardButton(
                f"{title} - {price_display}",
                callback_data=f"{CB_COURSE}{course_id}"
            )
        ])
    
    keyboard.append([InlineKeyboardButton("⬅️ Back to Categories", callback_data=CB_SHOW_CATEGORIES_MENU)])
    keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data=CB_BACK)])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await message.edit_text(
        f"📚 Courses in **{category_name}**:\n\nTap on a course to view details:",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
    # user_states[user.id] = State.VIEWING_COURSES # Already general enough
    log_action(str(user.id), "view_category_courses", details=f"Category: {category_name}")

async def show_dmca_policy(client, message: Message):
    """Display the DMCA & Copyright Policy from MongoDB."""
    user = message.from_user # For logging context
    db = get_db()
    if not db:
        await message.reply("Database error. Please try again later.", quote=True)
        return

    bot_settings_collection = db[COLLECTIONS["bot_settings"]]
    policy_text = "No DMCA/Policy text has been set by the admin yet."

    try:
        policy_setting_doc = bot_settings_collection.find_one({"key": "dmca_policy_text"})
        if policy_setting_doc and policy_setting_doc.get("value"):
            policy_text = policy_setting_doc["value"]
    except Exception as e:
        print(f"Error fetching DMCA policy: {e}")
        # Use default policy_text in case of error

    await message.reply(
        f"📜 **DMCA Copyright & Policy**\n\n{policy_text}",
        quote=True,
        reply_markup=await get_main_menu_markup(), # Static markup
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True
    )
    log_action(str(user.id), "view_dmca_policy")

async def handle_request_course_button(client, message: Message):
    """Handles the 'Request Course' button press.
    Sets user state to await their course request details.
    """
    user = message.from_user
    await message.reply(
        "✍️ Please describe the course you would like to request. Include as much detail as possible (e.g., name, instructor, topics).",
        quote=True,
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ Cancel Request")]], resize_keyboard=True, one_time_keyboard=True)
    )
    user_states[user.id] = State.AWAITING_COURSE_REQUEST
    log_action(str(user.id), "pressed_request_course_button")

async def save_course_request(client, message: Message, user_pyrogram, request_text: str):
    """Saves the user's course request to the MongoDB database."""
    if request_text.lower() == "❌ cancel request": # Check for cancellation first
        await message.reply(
            "✅ Course request cancelled.",
            quote=True,
            reply_markup=await get_main_menu_markup() # Static markup
        )
        user_states[user_pyrogram.id] = State.IDLE
        log_action(str(user_pyrogram.id), "cancelled_course_request")
        return

    db = get_db()
    if not db:
        await message.reply("Database error. Could not save request. Please try again later.", quote=True)
        user_states[user_pyrogram.id] = State.IDLE # Reset state on error
        return

    # Get or create user (already MongoDB compatible)
    db_user_doc = await get_or_create_user(user_pyrogram) 
    if not db_user_doc:
        await message.reply("Could not retrieve your user information to save the request. Please try again.", quote=True)
        user_states[user_pyrogram.id] = State.IDLE # Reset state on error
        return

    course_requests_collection = db[COLLECTIONS["course_requests"]]
    
    new_request_document = {
        "user_id": db_user_doc["_id"],  # Store ObjectId of the user
        "telegram_user_id": db_user_doc["telegram_id"], # Denormalize for easier admin lookup
        "username": db_user_doc.get("username"),
        "first_name": db_user_doc.get("first_name"),
        "request_text": request_text,
        "timestamp": datetime.datetime.now(datetime.UTC),
        "status": "pending" # Default status for new requests
    }

    try:
        result = course_requests_collection.insert_one(new_request_document)
        request_id = result.inserted_id
        print(f"Course request {request_id} from user {db_user_doc['telegram_id']} saved.")

        await message.reply(
            "✅ Thank you! Your course request has been submitted. Our admin team will review it.",
            quote=True,
            reply_markup=await get_main_menu_markup() # Static markup
        )
    except Exception as e:
        print(f"Error inserting course request into MongoDB: {e}")
        await message.reply("An error occurred while submitting your course request. Please contact support.", quote=True)
    
    user_states[user_pyrogram.id] = State.IDLE # Reset state after submission or error
    # Log action, even if DB insert failed, to note the attempt
    log_action(str(user_pyrogram.id), "submitted_course_request", details=request_text[:200])

# Main function to run the bot
async def main():
    await app.start()
    print("Bot started!")
    
    # Keep the bot running
    await asyncio.sleep(999999)
    
    await app.stop()

if __name__ == "__main__":
    app.run() 
