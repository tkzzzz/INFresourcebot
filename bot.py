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
# Use DIRECT Galaxy Harvester links to avoid FeedBurner "Invalid Token" errors
RSS_FEED_URLS = [
    "https://galaxyharvester.net/feedMineral.py",
    "https://galaxyharvester.net/feedChemical.py",
    "https://galaxyharvester.net/feedFlora.py",
    "https://galaxyharvester.net/feedGas.py",
    "https://galaxyharvester.net/feedWater.py",
    "https://galaxyharvester.net/feedEnergy.py"
]
TARGET_SERVER_NAME = "SWG Infinity"
CHECK_INTERVAL_SECONDS = 60 
MAX_SEEN_ENTRIES = 500

# --- Environment Variables ---
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
try:
    DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", 0))
except (ValueError, TypeError):
    DISCORD_CHANNEL_ID = 0

# --- Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True 
bot = commands.Bot(command_prefix="!ghrep ", intents=intents)
seen_entry_guids = []

# --- Helper Functions ---
def parse_resource_values(entry):
    try:
        if not hasattr(entry, 'content') or not entry.content:
            return None, None
        content_html = entry.content[0].get('value', '')
        pattern = r'([A-Z]{2})[\s:]+(\d+)(?:\s*\(\d+%\))?'
        matches = re.findall(pattern, content_html)
        if not matches: return None, None
        highest_val, highest_stat = 0, None
        for stat, val_str in matches:
            val = int(val_str)
            if val > highest_val: highest_val, highest_stat = val, stat
        return highest_stat, highest_val
    except: return None, None

@bot.event
async def on_ready():
    logging.info(f'{bot.user.name} connected.')
    if DISCORD_CHANNEL_ID != 0:
        fetch_rss_feed_task.start()

@tasks.loop(seconds=CHECK_INTERVAL_SECONDS)
async def fetch_rss_feed_task():
    global seen_entry_guids
    channel = bot.get_channel(DISCORD_CHANNEL_ID)
    if not channel: return

    for feed_url in RSS_FEED_URLS:
        try:
            # Added custom user-agent to avoid being blocked by the server
            feed = await bot.loop.run_in_executor(None, lambda: feedparser.parse(feed_url, agent='Mozilla/5.0'))
            
            if feed.bozo:
                logging.error(f"Feed error {feed_url}: {feed.bozo_exception}")
                continue

            new_entries = []
            for entry in feed.entries:
                guid = entry.get("guid", entry.link)
                if guid not in seen_entry_guids:
                    if TARGET_SERVER_NAME.lower() in entry.title.lower():
                        new_entries.append(entry)
                    seen_entry_guids.append(guid) # Mark as seen immediately

            if new_entries:
                for entry_to_post in new_entries:
                    stat, val = parse_resource_values(entry_to_post)
                    await channel.send(entry_to_post.link)
                    if stat: await channel.send(f"Highest value = **{stat} {val}**")
            
        except Exception as e:
            logging.error(f"Error in {feed_url}: {e}")

    if len(seen_entry_guids) > MAX_SEEN_ENTRIES:
        seen_entry_guids = seen_entry_guids[-MAX_SEEN_ENTRIES:]

@fetch_rss_feed_task.before_loop
async def before_fetch_rss_feed_task():
    await bot.wait_until_ready()

if __name__ == "__main__":
    bot.run(DISCORD_BOT_TOKEN)
