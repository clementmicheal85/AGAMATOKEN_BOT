import os
import asyncio
import logging
from web3 import Web3, WebSocketProvider
from web3.middleware import geth_poa_middleware
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, ApplicationBuilder

# --- Configuration (Load from Environment Variables for Security) ---
# It's crucial to set these as environment variables on your hosting platform (e.g., Render.com)
#
# TEL_BOT_TOKEN: Your Telegram bot token (e.g., 8322021979:AAEV...)
# TEL_CHAT_ID: The chat ID of the group/channel where alerts will be sent
# QN_WSS_URL: Your QuickNode WebSocket (WSS) URL for BNB Smart Chain (e.g., wss://...)
# TOKEN_CONTRACT_ADDRESS: The address of your "agama coin" token contract
#
# Example of how to get your Telegram chat ID:
# 1. Add your bot to the group or channel.
# 2. Send a message in the group.
# 3. Open this URL in your browser: https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates
#    (Replace <YOUR_BOT_TOKEN> with your token)
# 4. Look for the "chat" object in the JSON response. The "id" field is your chat ID.
#    It will be a negative number.

TELEGRAM_BOT_TOKEN = os.environ.get("TEL_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TEL_CHAT_ID")
QUICKNODE_WSS_URL = os.environ.get("QN_WSS_URL")
TOKEN_CONTRACT_ADDRESS = os.environ.get("TOKEN_CONTRACT_ADDRESS")

# --- Constants ---
MIN_BNB_PURCHASE = 0.025
AGAMA_LOGO_URL = "https://www.agamacoin.com/agama-logo-new.png"
BSC_SCAN_TOKEN_URL = "https://bscscan.com/token/0x2119de8f257d27662991198389E15Bf8d1F4aB24"

# --- Global Variables ---
w3_http = None

# Set up logging for better debugging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Telegram Bot Command Handlers ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Sends a welcome message and introduction when the /start command is issued.
    Also serves as the 'command button' the user requested.
    """
    await update.message.reply_text(
        f"👋 Welcome to the Agama Coin Bot! 👋\n\n"
        f"I'm here to provide real-time presale buy alerts and periodic reminders.\n"
        f"Use /buynow to get the presale link.\n"
        f"Use /remind to manually send a buy reminder to the channel."
    )
    logger.info("Received /start command.")

async def buy_now_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Sends the presale link when the /buynow command is issued.
    """
    message = (
        f"🚀 *Agama Coin Presale is Live!* 🚀\n\n"
        f"Secure your position and become an early holder.\n\n"
        f"➡️ [Buy Now!]({BSC_SCAN_TOKEN_URL})"
    )
    await context.bot.send_photo(
        chat_id=update.message.chat_id,
        photo=AGAMA_LOGO_URL,
        caption=message,
        parse_mode=ParseMode.MARKDOWN
    )
    logger.info("Received /buynow command.")

async def send_reminder_to_channel(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Sends a reminder message to the Telegram channel.
    This function is scheduled to run every 30 minutes.
    """
    try:
        message = (
            f"⏰ *Reminder*: The Presale is Live! ⏰\n\n"
            f"Don't miss your chance to be an early holder of Agama Coin! "
            f"The future of decentralized finance starts here.\n\n"
            f"➡️ [Buy Now and Join the Journey!]({BSC_SCAN_TOKEN_URL})"
        )
        await context.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=message,
            parse_mode=ParseMode.MARKDOWN
        )
        logger.info("Sent 30-minute reminder.")
    except Exception as e:
        logger.error(f"Error sending reminder: {e}")

# --- Blockchain Monitoring Functions ---
def handle_new_block(block, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Processes a new block to check for qualifying transactions.
    This function is called by the `listen_for_new_blocks` coroutine.
    """
    try:
        logger.info(f"Processing block {block.number} with {len(block.transactions)} transactions.")

        for tx in block.transactions:
            # Check if the transaction is a direct transfer of BNB to our token contract
            # and if the amount is greater than the minimum purchase threshold.
            if tx.to and tx.to.lower() == TOKEN_CONTRACT_ADDRESS.lower():
                bnb_value = w3_http.from_wei(tx['value'], 'ether')
                if bnb_value >= MIN_BNB_PURCHASE:
                    tx_hash = w3_http.to_hex(tx['hash'])
                    buyer_address = tx['from']
                    logger.info(f"Found a qualifying transaction: {tx_hash} from {buyer_address} for {bnb_value} BNB.")
                    
                    # Schedule the Telegram alert task
                    asyncio.create_task(send_telegram_alert(context.bot, tx_hash, bnb_value, buyer_address))
    except Exception as e:
        logger.error(f"Error handling new block {block.number}: {e}")

async def send_telegram_alert(bot_instance, tx_hash, amount, buyer_address):
    """
    Sends a professional and creative buy alert to the Telegram channel.
    """
    try:
        message = (
            f"🚀 *New Buy Alert!* 🚀\n\n"
            f"A true believer just joined the Agama Army! A savvy investor just acquired some $AGAMA!\n\n"
            f"💰 *Amount*: {amount:.3f} BNB\n"
            f"👤 *Buyer*: `{buyer_address[:6]}...{buyer_address[-4:]}`\n"
            f"🔗 *Transaction*: [View on BscScan](https://bscscan.com/tx/{tx_hash})\n"
            f"📈 *Become an early holder*: [Buy $AGAMA now!]({BSC_SCAN_TOKEN_URL})"
        )

        await bot_instance.send_photo(
            chat_id=TELEGRAM_CHAT_ID,
            photo=AGAMA_LOGO_URL,
            caption=message,
            parse_mode=ParseMode.MARKDOWN,
            disable_notification=False
        )
        logger.info(f"Sent new buy alert for tx: {tx_hash}")
    except Exception as e:
        logger.error(f"Error sending Telegram alert: {e}")

async def listen_for_new_blocks(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Sets up a WebSocket connection to QuickNode and listens for new blocks.
    This runs as a long-running task in the main application loop.
    """
    global w3_http
    
    while True:
        try:
            logger.info("Connecting to QuickNode via WebSocket...")
            async with WebSocketProvider(QUICKNODE_WSS_URL) as provider:
                w3_ws = Web3(provider)
                w3_ws.middleware_onion.inject(geth_poa_middleware, layer=0)
                
                # Check for an active connection before subscribing
                if not await w3_ws.is_connected():
                    raise ConnectionError("Failed to connect to QuickNode WebSocket.")
                
                new_block_filter = await w3_ws.eth.subscribe('newHeads')
                logger.info("Successfully subscribed to new block headers.")

                while True:
                    try:
                        new_block_header = await new_block_filter.receive()
                        block_number = new_block_header['number']
                        
                        # Get the full block using a separate HTTP provider to avoid blocking the WebSocket
                        block = w3_http.eth.get_block(block_number, full_transactions=True)
                        handle_new_block(block, context)
                    except asyncio.CancelledError:
                        logger.warning("WebSocket connection was cancelled.")
                        raise # Re-raise to allow the outer loop to handle cleanup
                    except Exception as e:
                        logger.error(f"Error receiving new block: {e}")
                        # Exponential backoff for retries
                        await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"Initial connection to QuickNode failed: {e}")
            logger.info("Retrying connection in 5 seconds...")
            await asyncio.sleep(5)

# --- Main Entry Point ---
async def main() -> None:
    """
    The main function that sets up and runs the bot.
    """
    global w3_http

    # Ensure all required environment variables are set
    if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, QUICKNODE_WSS_URL, TOKEN_CONTRACT_ADDRESS]):
        logger.error("Error: One or more required environment variables are not set.")
        logger.error("Please set TEL_BOT_TOKEN, TEL_CHAT_ID, QN_WSS_URL, and TOKEN_CONTRACT_ADDRESS.")
        exit(1)

    logger.info("Bot is starting...")
    
    # Initialize the synchronous Web3 HTTP provider
    try:
        w3_http = Web3(Web3.HTTPProvider(QUICKNODE_WSS_URL.replace("wss://", "https://")))
        w3_http.middleware_onion.inject(geth_poa_middleware, layer=0)
        if not w3_http.is_connected():
            raise Exception("Failed to connect to QuickNode via HTTP.")
        logger.info("Connected to QuickNode via HTTP.")
    except Exception as e:
        logger.error(f"Error initializing Web3 HTTP provider: {e}")
        exit(1)

    # Build the Telegram Application
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("buynow", buy_now_command))
    
    # Schedule the 30-minute reminder job
    job_queue = application.job_queue
    job_queue.run_repeating(send_reminder_to_channel, interval=1800, first=5) # 1800 seconds = 30 minutes

    # Start the blockchain listener as a background task
    application.add_post_init(lambda app: asyncio.create_task(listen_for_new_blocks(app)))

    # Start the bot using long polling
    logger.info("Starting Telegram bot with long polling...")
    await application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    except Exception as e:
        logger.critical(f"A critical error occurred in the main loop: {e}")
