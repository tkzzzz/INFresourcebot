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
RSS_FEED_URL = "https://feeds.feedburner.com/GalaxyHarvesterResourceActivity"
TARGET_SERVER_NAME = "SWG Infinity"
CHECK_INTERVAL_SECONDS = 60
MAX_SEEN_ENTRIES = 200
STARTUP_BATCH_SIZE = 5  # Number of recent items to post when the bot restarts

# --- Environment Variables ---
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
try:
    DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", 0))
except ValueError:
    logging.error("DISCORD_CHANNEL_ID is not a valid integer.")
    DISCORD_CHANNEL_ID = 0

# --- Bot Setup ---
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!ghrep ", intents=intents)
seen_entry_guids = []

def get_entry_content(entry):
    """Helper to safely extract text content from an RSS entry."""
    # Try the 'content' list (Atom standard)
    if hasattr(entry, 'content') and entry.content:
        return entry.content[0].get('value', '')
    
    # Try 'summary' (RSS standard)
    if hasattr(entry, 'summary'):
        return entry.summary

    # Try 'description' (Legacy RSS)
    if hasattr(entry, 'description'):
        return entry.description
        
    return ""

def parse_resource_values(entry):
    """Parse resource values from RSS entry content and return highest value info."""
    try:
        content_html = get_entry_content(entry)
        
        if not content_html:
            logging.debug(f"No content found for entry: {entry.get('title', 'Unknown')}")
            return None, None
        
        # Pattern to match resource stats (e.g., "DR: 780", "PE 102", "OQ 500")
        pattern = r'([A-Z]{2})[\s:]+(\d+)(?:\s*\(\d+%\))?'
        matches = re.findall(pattern, content_html)
        
        if not matches:
            return None, None
        
        # Find the highest value
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

async def post_entry_to_discord(channel, entry):
    """Refactored logic to post a single entry to Discord."""
    logging.info(f"Posting entry: {entry.title}")
    
    # Parse resource values
    highest_stat, highest_value = parse_resource_values(entry)
    
    try:
        # Send the URL first (Discord unfurls it)
        await channel.send(entry.link)
        
        # Send additional message with highest value if found
        if highest_stat and highest_value:
            await channel.send(f"Highest value = **{highest_stat} {highest_value}**")
            
    except discord.Forbidden:
        logging.error(f"Bot lacks permission to send messages in channel {DISCORD_CHANNEL_ID}.")
    except discord.HTTPException as e:
        logging.error(f"Failed to send message: {e}")

@bot.event
async def on_ready():
    logging.info(f'{bot.user.name} has connected to Discord!')
    if DISCORD_CHANNEL_ID != 0:
        fetch_rss_feed_task.start()

@tasks.loop(seconds=CHECK_INTERVAL_SECONDS)
async def fetch_rss_feed_task():
    global seen_entry_guids
    if DISCORD_CHANNEL_ID == 0: return

    try:
        feed = await bot.loop.run_in_executor(None, feedparser.parse, RSS_FEED_URL)
        
        if feed.bozo:
            logging.error(f"Error parsing RSS feed: {feed.bozo_exception}")
            return

        channel = bot.get_channel(DISCORD_CHANNEL_ID)
        if not channel:
            logging.error(f"Channel ID {DISCORD_CHANNEL_ID} not found.")
            return

        # filter for target server
        new_entries = []
        for entry in feed.entries:
            guid = entry.get("guid", entry.link)
            if guid not in seen_entry_guids:
                if TARGET_SERVER_NAME.lower() in entry.title.lower():
                    new_entries.append(entry)

        # Update seen list with current feed content so we don't re-post old stuff later
        current_guids = [e.get("guid", e.link) for e in feed.entries]
        # Extend seen list but keep it trimmed
        seen_entry_guids.extend([g for g in current_guids if g not in seen_entry_guids])
        if len(seen_entry_guids) > MAX_SEEN_ENTRIES:
            seen_entry_guids = seen_entry_guids[-MAX_SEEN_ENTRIES:]

        # Sort and post new entries
        if new_entries:
            logging.info(f"Found {len(new_entries)} new entries.")
            # Sort by published date
            new_entries.sort(key=lambda e: e.get("published_parsed") or e.get("updated_parsed"))
            
            for entry in new_entries:
                await post_entry_to_discord(channel, entry)

    except Exception as e:
        logging.exception("Error in RSS loop:")

@fetch_rss_feed_task.before_loop
async def startup_batch_post():
    """Runs once before the loop starts to post the 'batch' of recent items."""
    global seen_entry_guids
    await bot.wait_until_ready()
    
    if DISCORD_CHANNEL_ID == 0: return
    
    logging.info("Checking for recent items to batch post on startup...")
    try:
        feed = await bot.loop.run_in_executor(None, feedparser.parse, RSS_FEED_URL)
        channel = bot.get_channel(DISCORD_CHANNEL_ID)

        if not channel or not feed.entries:
            return

        # 1. Filter relevant entries for your server
        relevant_entries = [e for e in feed.entries if TARGET_SERVER_NAME.lower() in e.title.lower()]
        
        # 2. Sort them by date (oldest to newest)
        relevant_entries.sort(key=lambda e: e.get("published_parsed") or e.get("updated_parsed"))

        # 3. Take the last X entries (most recent)
        batch_to_post = relevant_entries[-STARTUP_BATCH_SIZE:] if len(relevant_entries) > 0 else []
        
        if batch_to_post:
            logging.info(f"Posting batch of {len(batch_to_post)} recent resources...")
            for entry in batch_to_post:
                await post_entry_to_discord(channel, entry)
        else:
            logging.info("No relevant recent entries found for batch post.")

        # 4. Mark ALL entries in the feed as 'seen' so the loop doesn't double-post them
        seen_entry_guids = [e.get("guid", e.link) for e in feed.entries]
        
    except Exception as e:
        logging.exception("Error during startup batch:")

# --- Main Execution ---
def main():
    if not DISCORD_BOT_TOKEN:
        logging.critical("DISCORD_BOT_TOKEN not set.")
        return
    bot.run(DISCORD_BOT_TOKEN)

if __name__ == "__main__":
    main()
