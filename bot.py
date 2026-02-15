import discord
from discord.ext import commands, tasks
import feedparser
import os
import logging
import asyncio # Good to have for context
import re # For parsing resource values
from datetime import datetime, timezone # For sorting entries by date

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Configuration ---
RSS_FEED_URL = "https://feeds.feedburner.com/GalaxyHarvesterResourceActivity"
TARGET_SERVER_NAME = "SWG Infinity"
CHECK_INTERVAL_SECONDS = 120
MAX_SEEN_ENTRIES = 200

# --- Environment Variables ---
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
try:
    DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", 0))
except ValueError:
    logging.error("DISCORD_CHANNEL_ID is not a valid integer. Please check your environment variables.")
    DISCORD_CHANNEL_ID = 0

# --- Bot Setup ---
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!ghrep ", intents=intents)
seen_entry_guids = []

def parse_resource_values(entry):
    """Parse resource values from RSS entry content and return highest value info."""
    try:
        if not hasattr(entry, 'content') or not entry.content:
            logging.debug("Entry has no content attribute or content is empty")
            return None, None
        
        content_html = entry.content[0].get('value', '')
        if not content_html:
            logging.debug("Content HTML is empty")
            return None, None
        
        # Log the actual content being parsed for debugging
        logging.info(f"Parsing content: {repr(content_html[:500])}")  # First 500 chars
        
        # Pattern to match resource stats in both formats:
        # - "DR: 780 (78%)" (with colon and percentage)
        # - "PE 102" (simple space-separated format)
        # - "OQ 500" (without percentage)
        pattern = r'([A-Z]{2})[\s:]+(\d+)(?:\s*\(\d+%\))?'
        matches = re.findall(pattern, content_html)
        
        logging.info(f"Regex matches found: {matches}")
        
        if not matches:
            logging.warning("No resource value matches found in content")
            return None, None
        
        # Find the highest value
        highest_value = 0
        highest_stat = None
        
        for stat, value_str in matches:
            value = int(value_str)
            logging.debug(f"Processing {stat}: {value}")
            if value > highest_value:
                highest_value = value
                highest_stat = stat
        
        logging.info(f"Determined highest value: {highest_stat} {highest_value}")
        return highest_stat, highest_value
    
    except Exception as e:
        logging.warning(f"Error parsing resource values: {e}")
        return None, None

@bot.event
async def on_ready():
    """Called when the bot successfully connects to Discord."""
    logging.info(f'{bot.user.name} has connected to Discord!')
    if DISCORD_CHANNEL_ID == 0:
        logging.error("DISCORD_CHANNEL_ID is not set or invalid. Bot will not be able to send messages.")
    else:
        logging.info(f'Monitoring RSS feed for "{TARGET_SERVER_NAME}" updates.')
        logging.info(f'Messages will be posted to channel ID: {DISCORD_CHANNEL_ID}')
        channel = bot.get_channel(DISCORD_CHANNEL_ID)
        if not channel:
            logging.warning(f"Could not find channel with ID {DISCORD_CHANNEL_ID}. Messages will not be sent.")
        fetch_rss_feed_task.start()

@tasks.loop(seconds=CHECK_INTERVAL_SECONDS)
async def fetch_rss_feed_task():
    """Periodically fetches and processes the RSS feed."""
    global seen_entry_guids
    if DISCORD_CHANNEL_ID == 0:
        logging.warning("Skipping RSS fetch: DISCORD_CHANNEL_ID not set.")
        return

    logging.info(f"Fetching RSS feed: {RSS_FEED_URL}")
    try:
        feed = await bot.loop.run_in_executor(None, feedparser.parse, RSS_FEED_URL)
        
        if feed.bozo:
            logging.error(f"Error parsing RSS feed. Details: {feed.bozo_exception}")
            return

        channel = bot.get_channel(DISCORD_CHANNEL_ID)
        if not channel:
            logging.error(f"Channel ID {DISCORD_CHANNEL_ID} not found. Cannot send messages.")
            return

        new_entries_to_post = []
        for entry in feed.entries:
            entry_guid = entry.get("guid", entry.link)
            if entry_guid not in seen_entry_guids:
                if TARGET_SERVER_NAME.lower() in entry.title.lower():
                    new_entries_to_post.append(entry)
        
        current_fetch_guids = [e.get("guid", e.link) for e in feed.entries]
        for guid_from_fetch in current_fetch_guids:
            if guid_from_fetch not in seen_entry_guids:
                seen_entry_guids.append(guid_from_fetch)
        
        if new_entries_to_post:
            logging.info(f"Found {len(new_entries_to_post)} new relevant entries for '{TARGET_SERVER_NAME}'.")
            
            def get_sort_key(e): # For sorting entries by publication date
                dt_struct = e.get("published_parsed") or e.get("updated_parsed")
                if dt_struct:
                    try:
                        return datetime(*dt_struct[:6], tzinfo=timezone.utc)
                    except ValueError:
                        return datetime.min.replace(tzinfo=timezone.utc)
                return datetime.min.replace(tzinfo=timezone.utc)

            for entry_to_post in sorted(new_entries_to_post, key=get_sort_key):
                logging.info(f"Posting URL for entry: {entry_to_post.title} -> {entry_to_post.link}")

                # Parse resource values to find highest
                highest_stat, highest_value = parse_resource_values(entry_to_post)
                
                # Send the URL first. Discord will attempt to unfurl it.
                try:
                    await channel.send(entry_to_post.link)
                    
                    # Send additional message with highest value if found
                    if highest_stat and highest_value:
                        await channel.send(f"Highest value = **{highest_stat} {highest_value}**")
                        logging.info(f"Highest value for {entry_to_post.title}: {highest_stat} {highest_value}")
                    
                except discord.Forbidden:
                    logging.error(f"Bot lacks permission to send messages in channel {DISCORD_CHANNEL_ID}.")
                    break 
                except discord.HTTPException as e:
                    logging.error(f"Failed to send message due to HTTPException: {e}")
        else:
            logging.info("No new relevant entries found in this check.")

        if len(seen_entry_guids) > MAX_SEEN_ENTRIES:
            logging.info(f"Trimming seen_entry_guids. Old size: {len(seen_entry_guids)}")
            seen_entry_guids = seen_entry_guids[-MAX_SEEN_ENTRIES:]
            logging.info(f"New size after trimming: {len(seen_entry_guids)}")

    except aiohttp.ClientError as e: # Specific error for network issues with aiohttp
        logging.error(f"Network error during RSS fetch (aiohttp.ClientError): {e}")
    except Exception as e:
        logging.exception("An unexpected error occurred during RSS fetch or processing:")

@fetch_rss_feed_task.before_loop
async def before_fetch_rss_feed_task():
    logging.info("Waiting for bot to be ready...")
    await bot.wait_until_ready()
    logging.info("Bot ready! Starting fresh check (this will post recent resources).")
    # We leave seen_entry_guids empty so it 'catches' current feed items

# --- Main Execution ---
def main():
    if not DISCORD_BOT_TOKEN:
        logging.critical("FATAL ERROR: DISCORD_BOT_TOKEN environment variable not set.")
        return
    if DISCORD_CHANNEL_ID == 0:
        logging.critical("FATAL ERROR: DISCORD_CHANNEL_ID environment variable not set or invalid.")
        return
    
    logging.info("Attempting to start the bot...")
    try:
        bot.run(DISCORD_BOT_TOKEN)
    except discord.LoginFailure:
        logging.critical("Login failed: Invalid DISCORD_BOT_TOKEN.")
    except discord.PrivilegedIntentsRequired:
        logging.critical("Privileged intents are required but not enabled.")
    except Exception as e:
        logging.critical(f"An critical error occurred while trying to run the bot: {e}", exc_info=True)

if __name__ == "__main__":
    main()


