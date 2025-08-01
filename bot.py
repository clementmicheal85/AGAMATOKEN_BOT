import os
import time
import requests
import asyncio
from threading import Timer
from web3 import Web3, WebsocketProvider
from web3.middleware import geth_poa_middleware
from telegram import Bot
from telegram.error import TelegramError

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
# 4. Look for the "chat" object in the JSON response. The "id" field is your chat ID. It will be a negative number.

TELEGRAM_BOT_TOKEN = os.environ.get("TEL_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TEL_CHAT_ID")
QUICKNODE_WSS_URL = os.environ.get("QN_WSS_URL")
TOKEN_CONTRACT_ADDRESS = os.environ.get("TOKEN_CONTRACT_ADDRESS")

# Constants
MIN_BNB_PURCHASE = 0.025
AGAMA_LOGO_URL = "https://www.agamacoin.com/agama-logo-new.png"
BSC_SCAN_TOKEN_URL = "https://bscscan.com/token/0x2119de8f257d27662991198389E15Bf8d1F4aB24"

# --- Global Variables ---
bot = Bot(token=TELEGRAM_BOT_TOKEN)
w3 = None

# --- Telegram Bot Functions ---
async def send_telegram_alert(tx_hash, amount, buyer_address):
    """
    Sends a professional and creative buy alert to the Telegram channel.
    """
    try:
        # Generate a creative message
        message = (
            f"🚀 *New Buy Alert!* 🚀\n\n"
            f"A true believer just joined the Agama Army! A savvy investor just acquired some $AGAMA!\n\n"
            f"💰 *Amount*: {amount:.3f} BNB\n"
            f"👤 *Buyer*: `{buyer_address[:6]}...{buyer_address[-4:]}`\n"
            f"🔗 *Transaction*: [View on BscScan](https://bscscan.com/tx/{tx_hash})\n"
            f"📈 *Become an early holder*: [Buy $AGAMA now!]({BSC_SCAN_TOKEN_URL})"
        )

        # Send the photo with the message as a caption
        await bot.send_photo(
            chat_id=TELEGRAM_CHAT_ID,
            photo=AGAMA_LOGO_URL,
            caption=message,
            parse_mode='Markdown',
            disable_notification=False # Set to True to send silently
        )
        print(f"Sent new buy alert for tx: {tx_hash}")

    except TelegramError as e:
        print(f"Error sending Telegram alert: {e}")
    except Exception as e:
        print(f"An unexpected error occurred in send_telegram_alert: {e}")


def send_reminder():
    """
    Sends a reminder message to the Telegram channel.
    This function will be called every 30 minutes.
    """
    try:
        message = (
            f"⏰ *Reminder*: The Presale is Live! ⏰\n\n"
            f"Don't miss your chance to be an early holder of Agama Coin! "
            f"The future of decentralized finance starts here.\n\n"
            f"➡️ [Buy Now and Join the Journey!]({BSC_SCAN_TOKEN_URL})"
        )
        asyncio.run(bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=message,
            parse_mode='Markdown'
        ))
        print("Sent 30-minute reminder.")
    except TelegramError as e:
        print(f"Error sending reminder: {e}")
    except Exception as e:
        print(f"An unexpected error occurred in send_reminder: {e}")

    # Reset the timer for the next 30-minute interval
    timer = Timer(30 * 60, send_reminder)
    timer.daemon = True # Allow the timer to exit with the main program
    timer.start()

# --- Blockchain Monitoring Functions ---
def handle_new_block(block_number):
    """
    Processes a new block to check for qualifying transactions.
    """
    try:
        block = w3.eth.get_block(block_number, full_transactions=True)
        print(f"Processing block {block_number} with {len(block.transactions)} transactions.")

        for tx in block.transactions:
            # Check if the transaction is a direct transfer of BNB to our token contract
            # and if the amount is greater than the minimum purchase threshold.
            if tx.to and tx.to.lower() == TOKEN_CONTRACT_ADDRESS.lower():
                bnb_value = w3.fromWei(tx['value'], 'ether')
                if bnb_value >= MIN_BNB_PURCHASE:
                    tx_hash = w3.toHex(tx['hash'])
                    buyer_address = tx['from']
                    print(f"Found a qualifying transaction: {tx_hash} from {buyer_address} for {bnb_value} BNB.")
                    # Run the async Telegram function
                    asyncio.run(send_telegram_alert(tx_hash, bnb_value, buyer_address))
    except Exception as e:
        print(f"Error handling new block {block_number}: {e}")

async def listen_for_new_blocks():
    """
    Sets up a WebSocket connection to QuickNode and listens for new blocks.
    This is a real-time method and is more efficient than polling.
    """
    print("Connecting to QuickNode via WebSocket...")
    try:
        # Use web3.py's WebsocketProvider to handle the subscription
        async with WebsocketProvider(QUICKNODE_WSS_URL) as provider:
            w3_ws = Web3(provider)
            # Necessary for chains that use proof-of-authority like BSC
            w3_ws.middleware_onion.inject(geth_poa_middleware, layer=0)
            
            # Subscribe to new block headers
            new_block_filter = await w3_ws.eth.subscribe('newHeads')

            while True:
                try:
                    new_block_header = await new_block_filter.receive()
                    block_number = new_block_header['number']
                    # We can't do blocking calls inside this async loop, so we'll run
                    # the transaction processing in a separate, non-async context.
                    # This is just an example, a more robust solution would use
                    # a ThreadPoolExecutor or similar for heavy processing.
                    handle_new_block(block_number)
                except asyncio.CancelledError:
                    print("WebSocket connection was cancelled.")
                    break
                except Exception as e:
                    print(f"Error receiving new block: {e}")
                    # Implement exponential backoff for retries
                    time.sleep(2)
    except Exception as e:
        print(f"Initial connection to QuickNode failed: {e}")
        print("Retrying connection in 5 seconds...")
        time.sleep(5)
        asyncio.run(listen_for_new_blocks()) # Retry the connection

# --- Main Entry Point ---
if __name__ == "__main__":
    # Ensure all required environment variables are set
    if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, QUICKNODE_WSS_URL, TOKEN_CONTRACT_ADDRESS]):
        print("Error: One or more required environment variables are not set.")
        print("Please set TEL_BOT_TOKEN, TEL_CHAT_ID, QN_WSS_URL, and TOKEN_CONTRACT_ADDRESS.")
        exit(1)

    print("Bot is starting...")
    # Initialize the synchronous web3 instance for get_block calls
    try:
        w3 = Web3(Web3.HTTPProvider(QUICKNODE_WSS_URL.replace("wss://", "https://")))
        w3.middleware_onion.inject(geth_poa_middleware, layer=0)
        if not w3.is_connected():
            raise Exception("Failed to connect to QuickNode via HTTP.")
    except Exception as e:
        print(f"Error initializing Web3 HTTP provider: {e}")
        exit(1)

    # Start the 30-minute reminder timer
    print("Starting 30-minute reminder timer...")
    timer = Timer(30 * 60, send_reminder)
    timer.daemon = True
    timer.start()

    # Start listening for blockchain events in an infinite loop
    print("Starting blockchain listener...")
    asyncio.run(listen_for_new_blocks())
