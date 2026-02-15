import discord
from discord.ext import commands, tasks
import feedparser
import os
import logging
import asyncio
import re
from datetime import datetime, timezone

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Configuration ---
# Monitoring ALL official category feeds to ensure we see every resource type
RSS_FEED_URLS = [
    "https://feeds.feedburner.com/GalaxyHarvesterMineralResourceAdds",
    "https://feeds.feedburner.com/GalaxyHarvesterChemicalResourceAdds",
    "https://feeds.feedburner.com/GalaxyHarvesterFloraResourceAdds",
    "https://feeds.feedburner.com/GalaxyHarvesterGasResourceAdds",
    "https://feeds.feedburner.com/GalaxyHarvesterWaterResourceAdds",
    "https://feeds.feedburner.com/GalaxyHarvesterEnergyResourceAdds",
    "https://feeds.feedburner.com/GalaxyHarvesterCreatureResourceAdds"
]
TARGET_SERVER_NAME = "SWG Infinity"
CHECK_INTERVAL_SECONDS = 60 
MAX_SEEN_ENTRIES = 1000

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

def parse_resource_values(entry):
    """Extract stats and return the highest value found."""
    try:
        if not hasattr(entry, 'content') or not entry.content: return None, None
        content_html = entry.content[0].get('value', '')
        # Matches formats like "DR: 780" or "PE 102"
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
    logging.info(f'{bot.user.name} online. Monitoring Infinity resources...')
    if DISCORD_CHANNEL_ID != 0:
        if not fetch_rss_feed_task.is_running():
            fetch_rss_feed_task.start()

@tasks.loop(seconds=CHECK_INTERVAL_SECONDS)
async def fetch_rss_feed_task():
    global seen_entry_guids
    channel = bot.get_channel(DISCORD_CHANNEL_ID)
    if not channel: return

    for feed_url in RSS_FEED_URLS:
        try:
            # agent helps bypass 'invalid token'/interstitial errors from FeedBurner
            feed = await bot.loop.run_in_executor(None, lambda: feedparser.parse(feed_url, agent='Mozilla/5.0'))
            
            if feed.bozo:
                logging.error(f"Feed error {feed_url}: {feed.bozo_exception}")
                continue

            for entry in feed.entries:
                guid = entry.get("guid", entry.link)
                if guid not in seen_entry_guids:
                    if TARGET_SERVER_NAME.lower() in entry.title.lower():
                        logging.info(f"New Match: {entry.title}")
                        stat, val = parse_resource_values(entry)
                        await channel.send(entry.link)
                        if stat: await channel.send(f"Highest value = **{stat} {val}**")
                    seen_entry_guids.append(guid)

        except discord.Forbidden:
            logging.error("CRITICAL: Bot lacks permission to post in this channel.")
            break
        except Exception as e:
            logging.error(f"Error checking {feed_url}: {e}")

    if len(seen_entry_guids) > MAX_SEEN_ENTRIES:
        seen_entry_guids = seen_entry_guids[-MAX_SEEN_ENTRIES:]

@fetch_rss_feed_task.before_loop
async def before_fetch_rss_feed_task():
    await bot.wait_until_ready()

if __name__ == "__main__":
    if DISCORD_BOT_TOKEN and DISCORD_CHANNEL_ID:
        bot.run(DISCORD_BOT_TOKEN)
    else:
        logging.critical("Missing DISCORD_BOT_TOKEN or DISCORD_CHANNEL_ID.")
