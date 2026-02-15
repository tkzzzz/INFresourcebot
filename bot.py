import discord
from discord.ext import commands, tasks
import feedparser
import os
import logging
import asyncio
import re
from datetime import datetime, timezone
import aiohttp

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Configuration ---
# Monitoring specific category feeds separately to prevent "SWG Infinity" items from being pushed out
RSS_FEED_URLS = [
    "https://feeds.feedburner.com/GalaxyHarvesterMineralResourceAdds",
    "https://feeds.feedburner.com/GalaxyHarvesterChemicalResourceAdds",
    "https://feeds.feedburner.com/GalaxyHarvesterFloraResourceAdds",
    "https://feeds.feedburner.com/GalaxyHarvesterGasResourceAdds",
    "https://feeds.feedburner.com/GalaxyHarvesterWaterResourceAdds",
    "https://feeds.feedburner.com/GalaxyHarvesterEnergyResourceAdds"
]
TARGET_SERVER_NAME = "SWG Infinity"
CHECK_INTERVAL_SECONDS = 60  # Checked every minute for better accuracy
MAX_SEEN_ENTRIES = 500       # Increased capacity for multiple feeds

# --- Environment Variables ---
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
try:
    DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", 0))
except ValueError:
    logging.error("DISCORD_CHANNEL_ID is not a valid integer. Check environment variables.")
    DISCORD_CHANNEL_ID = 0

# --- Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True  # ENABLED: Fixed the intent warning from your logs
bot = commands.Bot(command_prefix="!ghrep ", intents=intents)
seen_entry_guids = []

def parse_resource_values(entry):
    """Parse resource values from RSS entry content and return highest value info."""
    try:
        if not hasattr(entry, 'content') or not entry.content:
            return None, None
        
        content_html = entry.content[0].get('value', '')
        if not content_html:
            return None, None
        
        # Pattern to match resource stats like "DR: 780" or "PE 102"
        pattern = r'([A-Z]{2})[\s:]+(\d+)(?:\s*\(\d+%\))?'
        matches = re.findall(pattern, content_html)
        
        if not matches:
            return None, None
        
        highest_value = 0
        highest_stat = None
        
        for stat, value_str in matches:
            value = int(value_str)
            if value > highest_value:
                highest_value = value
                highest_stat = stat
        
        return highest_stat, highest_value
    
    except Exception as e:
        logging.warning(f"Error parsing resource values: {e}")
        return None, None

@bot.event
async def on_ready():
    """Called when the bot successfully connects to Discord."""
    logging.info(f'{bot.user.name} has connected to Discord!')
    if DISCORD_CHANNEL_ID == 0:
        logging.error("DISCORD_CHANNEL_ID is not set.")
    else:
        logging.info(f'Monitoring all RSS feeds for "{TARGET_SERVER_NAME}" updates.')
        fetch_rss_feed_task.start()

@tasks.loop(seconds=CHECK_INTERVAL_SECONDS)
async def fetch_rss_feed_task():
    """Periodically fetches and processes multiple category RSS feeds."""
    global seen_entry_guids
    if DISCORD_CHANNEL_ID == 0:
        return

    channel = bot.get_channel(DISCORD_CHANNEL_ID)
    if not channel:
        logging.error(f"Channel ID {DISCORD_CHANNEL_ID} not found.")
        return

    # Loop through every category-specific feed
    for feed_url in RSS_FEED_URLS:
        logging.info(f"Fetching RSS feed: {feed_url}")
        try:
            feed = await bot.loop.run_in_executor(None, feedparser.parse, feed_url)
            
            if feed.bozo:
                logging.error(f"Error parsing feed {feed_url}: {feed.bozo_exception}")
                continue

            new_entries_to_post = []
            for entry in feed.entries:
                entry_guid = entry.get("guid", entry.link)
                # Check if it's new and matches the target server
                if entry_guid not in seen_entry_guids:
                    if TARGET_SERVER_NAME.lower() in entry.title.lower():
                        new_entries_to_post.append(entry)
            
            # Update seen list
            current_fetch_guids = [e.get("guid", e.link) for e in feed.entries]
            for guid_from_fetch in current_fetch_guids:
                if guid_from_fetch not in seen_entry_guids:
                    seen_entry_guids.append(guid_from_fetch)
            
            if new_entries_to_post:
                logging.info(f"Found {len(new_entries_to_post)} items in {feed_url}")
                
                def get_sort_key(e):
                    dt_struct = e.get("published_parsed") or e.get("updated_parsed")
                    if dt_struct:
                        return datetime(*dt_struct[:6], tzinfo=timezone.utc)
                    return datetime.min.replace(tzinfo=timezone.utc)

                for entry_to_post in sorted(new_entries_to_post, key=get_sort_key):
                    logging.info(f"Posting: {entry_to_post.title}")
                    highest_stat, highest_value = parse_resource_values(entry_to_post)
                    
                    try:
                        await channel.send(entry_to_post.link)
                        if highest_stat and highest_value:
                            await channel.send(f"Highest value = **{highest_stat} {highest_value}**")
                    except Exception as e:
                        logging.error(f"Failed to send message: {e}")
                        break 
            
        except aiohttp.ClientError as e:
            logging.error(f"Network error for {feed_url}: {e}")
        except Exception as e:
            logging.exception(f"Unexpected error for {feed_url}:")

    # Trim seen list to prevent memory growth
    if len(seen_entry_guids) > MAX_SEEN_ENTRIES:
        seen_entry_guids = seen_entry_guids[-MAX_SEEN_ENTRIES:]

@fetch_rss_feed_task.before_loop
async def before_fetch_rss_feed_task():
    """Wait for bot to be ready. Skipping pre-population to catch recent entries."""
    logging.info("Waiting for bot to be ready...")
    await bot.wait_until_ready()
    logging.info("Bot ready! Starting first check to catch current feed resources.")

# --- Main Execution ---
def main():
    if not DISCORD_BOT_TOKEN:
        logging.critical("DISCORD_BOT_TOKEN not set.")
        return
    if DISCORD_CHANNEL_ID == 0:
        logging.critical("DISCORD_CHANNEL_ID not set.")
        return
    
    logging.info("Attempting to start the bot...")
    try:
        bot.run(DISCORD_BOT_TOKEN)
    except Exception as e:
        logging.critical(f"Critical error: {e}")

if __name__ == "__main__":
    main()
