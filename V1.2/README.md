# Telegram Course Delivery Bot

A Telegram bot for selling and delivering online courses with an admin dashboard for management.

## Features

- Telegram bot interface for browsing and purchasing courses
- Admin dashboard for managing courses, users, and payments
- Multiple payment methods (UPI, Crypto, PayPal, COD, Gift Cards)
- Course search functionality
- Payment verification system

## Heroku Deployment Instructions

### Prerequisites

1. A Telegram Bot token (from [@BotFather](https://t.me/botfather))
2. Telegram API ID and API Hash (from [my.telegram.org](https://my.telegram.org))
3. A [Heroku](https://heroku.com) account

### Setup Steps

1. **Fork or Clone this Repository**
   
   First, fork or clone this repository to your GitHub account.

2. **Create a New Heroku App**

   Go to your Heroku dashboard and create a new app.

3. **Connect GitHub Repository**

   In your Heroku app, go to the "Deploy" tab and connect your GitHub repository.

4. **Add PostgreSQL Database**

   Go to the "Resources" tab and add the "Heroku Postgres" add-on (free tier is fine for testing).

5. **Configure Environment Variables**

   In the "Settings" tab, click on "Reveal Config Vars" and add the following variables:

   - `API_ID`: Your Telegram API ID
   - `API_HASH`: Your Telegram API Hash
   - `BOT_TOKEN`: Your Telegram Bot Token
   - `ADMIN_USERNAME`: Admin dashboard username (default: admin)
   - `ADMIN_PASSWORD`: Admin dashboard password (default: admin123)
   - `UPI_ID`: Your UPI ID for payments (if applicable)
   - `CRYPTO_ADDRESS`: Your cryptocurrency address (if applicable)
   - `PAYPAL_ID`: Your PayPal ID (if applicable)
   - `AUTO_APPROVE`: Set to "true" to auto-approve payments (default: false)

6. **Deploy Your App**

   Go back to the "Deploy" tab and click "Deploy Branch" at the bottom of the page.

7. **Scale Dynos**

   After deployment, go to the "Resources" tab and enable both the web and worker dynos:
   - `web`: Runs the admin dashboard
   - `worker`: Runs the Telegram bot

### Running Locally

To run the application locally:

1. Create a `.env` file in the project root with the required environment variables
2. Install dependencies: `pip install -r requirements.txt`
3. Run the admin dashboard: `python -m admin.app`
4. Run the Telegram bot: `python -m bot.bot`

## Removing Courses from Telegram Bot

To remove a course from the Telegram bot without deleting it from the database:

1. Log in to the admin dashboard
2. Go to "Courses"
3. Click the "Edit" button for the course you want to remove
4. Uncheck the "Active" checkbox at the bottom of the form
5. Click "Save Changes"

The course will remain in the database but won't be visible in the Telegram bot.

## Configuration Options

See the `config/config.py` file for all available configuration options.

## License

This project is licensed under the MIT License - see the LICENSE file for details. 