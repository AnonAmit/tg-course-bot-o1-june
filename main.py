import os
import sys
import asyncio
import threading
import subprocess
from pathlib import Path

# Add the project root to the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import bot and admin components
from bot.bot import app as bot_app
from database.init_db import initialize_database

def start_admin_dashboard():
    """Start the admin dashboard in a separate process"""
    admin_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "admin", "app.py")
    subprocess.Popen([sys.executable, admin_path])
    print("Admin dashboard started on http://localhost:5000")

def run_bot():
    """Run the Telegram bot"""
    print("Starting Telegram bot...")
    bot_app.run()

def main():
    """Main entry point for the application"""
    print("Initializing Course Delivery Bot...")
    
    # Create uploads directory if it doesn't exist
    uploads_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
    os.makedirs(uploads_dir, exist_ok=True)
    
    # Initialize the database
    print("Initializing database...")
    initialize_database()
    
    # Start admin dashboard in a separate thread
    print("Starting admin dashboard...")
    admin_thread = threading.Thread(target=start_admin_dashboard)
    admin_thread.daemon = True
    admin_thread.start()
    
    # Run the bot in the main thread
    run_bot()

if __name__ == "__main__":
    main() 