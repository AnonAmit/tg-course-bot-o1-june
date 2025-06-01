=== COURSE DELIVERY BOT TODO LIST ===
PHASE 01: DATABASE MIGRATION (SQLite to MongoDB) [In Progress]
a. Project Setup & Configuration [Completed]
    i. Update `todo.md` and `changelog.md` [x]
    ii. Modify `requirements.txt` (add `pymongo`, comment out SQLAlchemy related) [x]
    iii. Configure `config/config.py` for MongoDB (`MONGODB_URI`) [x]
b. Code Refactoring for MongoDB [Completed]
    i. `database/models.py` (from SQLAlchemy to Pymongo) [x]
    ii. `database/init_db.py` (for MongoDB initialization) [x]
    iii. `database/migration.py` (delete SQL migration script) [x]
    iv. `admin/app.py` (Flask admin panel - Pymongo) [x]
    v. `utils/helpers.py` (`log_action`, `format_course_info` for Pymongo) [x]
    vi. `bot/bot.py` (Telegram bot - Pymongo) [x]
c. Data Migration (SQLite to MongoDB) [Skipped - No existing SQLite data]
    i. Create a script `database/migrate_sqlite_to_mongo.py`. [N/A]
    ii. Implement logic to read data from SQLite tables. [N/A]
    iii. Implement logic to transform and insert data into MongoDB. [N/A]
    iv. Handle relationships. [N/A]
    v. Test the migration script. [N/A]
d. Testing & Deployment Preparation [In Progress]
    i. Run `database/init_db.py` to populate MongoDB with initial/sample data. [x]
    ii. Thoroughly test the Flask admin panel (`admin/app.py`) with MongoDB. [ ]
    iii. Thoroughly test the Telegram bot (`bot/bot.py`) with MongoDB. [ ]
    iv. Update `Procfile` if necessary (should be fine for MongoDB). [x]
    v. Update `Dockerfile` if necessary (ensure MongoDB driver dependencies are handled if any system-level ones are needed, though `pymongo` usually suffices). [ ]
    vi. Test deployment to Heroku with MongoDB Atlas. [ ]

PHASE 02: NEW FEATURE - ADMIN FUNCTIONS IN TELEGRAM BOT [ ]
a. Plan Admin Bot Features [ ]
    i. Define specific admin actions needed in the bot (e.g., view stats, manage users, approve payments, manage courses, etc.).
b. Implement Admin Authentication in Bot [ ]
    i. Create a secure way for admins to authenticate (e.g., command + password, user ID whitelist).
c. Develop Admin Command Handlers [ ]
    i. `/admin_dashboard` - Show summary/stats.
    ii. `/admin_users` - List users, view details, ban/unban.
    iii. `/admin_payments` - List pending payments, approve/reject.
    iv. `/admin_courses` - List courses, add/edit/delete (simplified version of web panel).
    v. `/admin_settings` - View/edit bot settings.
d. Create Admin-Specific Keyboards & Messages [ ]
e. Testing Admin Bot Features [ ]

PHASE 03: REVIEW & FINALIZATION [ ]
a. Code Review and Refinements [ ]
b. Final Testing (All Features) [ ]
c. Documentation Update (README, etc.) [ ] 