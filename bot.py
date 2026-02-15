import discord
from discord.ext import commands, tasks
import feedparser
import os
import logging
import re
import aiohttp
from bs4 import BeautifulSoup
from datetime import datetime, timezone

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Configuration ---
# Adding ?format=xml forces FeedBurner to return raw data instead of an HTML page
RSS_FEED_URLS = [
    "https://feeds.feedburner.com/GalaxyHarvesterMineralResourceAdds?format=xml",
    "https://feeds.feedburner.com/GalaxyHarvesterChemicalResourceAdds?format=xml",
    "https://feeds.feedburner.com/GalaxyHarvesterFloraResourceAdds?format=xml",
    "https://feeds.feedburner.com/GalaxyHarvesterGasResourceAdds?format=xml",
    "https://feeds.feedburner.com/GalaxyHarvesterWaterResourceAdds?format=xml",
    "https://feeds.feedburner.com/GalaxyHarvesterEnergyResourceAdds?format=xml",
    "https://feeds.feedburner.com/GalaxyHarvesterCreatureResourceAdds?format=xml"
]
TARGET_SERVER_NAME = "SWG Infinity"
CHECK_INTERVAL_SECONDS = 60 
MAX_SEEN_ENTRIES = 1000

# --- Environment Variables ---
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", 0))

# --- Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True 
bot = commands.Bot(command_prefix="!ghrep ", intents=intents)
seen_entry_guids = []

def parse_resource_values(entry):
    try:
        if not hasattr(entry, 'content') or not entry.content: return None, None
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
    logging.info(f'{bot.user.name} online. Monitoring Infinity resources...')
    if DISCORD_CHANNEL_ID != 0 and not fetch_rss_feed_task.is_running():
        fetch_rss_feed_task.start()

@tasks.loop(seconds=CHECK_INTERVAL_SECONDS)
async def fetch_rss_feed_task():
    global seen_entry_guids
    channel = bot.get_channel(DISCORD_CHANNEL_ID)
    if not channel: return

    # Realistic browser header to bypass bot detection
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/rss+xml, application/xml;q=0.9, */*;q=0.8'
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        for feed_url in RSS_FEED_URLS:
            try:
                async with session.get(feed_url, allow_redirects=True) as response:
                    if response.status != 200:
                        logging.error(f"HTTP {response.status} for {feed_url}")
                        continue
                    
                    raw_content = await response.text()
                    
                    # Debug: Check if we got HTML instead of XML
                    if raw_content.strip().startswith("<!DOCTYPE html") or "<html" in raw_content[:200]:
                        logging.warning(f"Warning: Received HTML instead of XML from {feed_url}. Check if the bot is blocked.")
                        continue

                    # Parse the fetched content
                    feed = feedparser.parse(raw_content)
                    
                    if feed.bozo:
                        # Attempt a 'clean' parse if the XML is slightly broken
                        soup = BeautifulSoup(raw_content, "xml")
                        feed = feedparser.parse(str(soup))
                        if feed.bozo:
                            logging.error(f"Feed parsing failed for {feed_url}: {feed.bozo_exception}")
                            continue

                    for entry in feed.entries:
                        guid = entry.get("guid", entry.link)
                        if guid not in seen_entry_guids:
                            if TARGET_SERVER_NAME.lower() in entry.title.lower():
                                logging.info(f"MATCH FOUND: {entry.title}")
                                stat, val = parse_resource_values(entry)
                                await channel.send(entry.link)
                                if stat: await channel.send(f"Highest value = **{stat} {val}**")
                            seen_entry_guids.append(guid)

            except Exception as e:
                logging.error(f"Error checking {feed_url}: {e}")

    if len(seen_entry_guids) > MAX_SEEN_ENTRIES:
        seen_entry_guids = seen_entry_guids[-MAX_SEEN_ENTRIES:]

@fetch_rss_feed_task.before_loop
async def before_fetch_rss_feed_task():
    await bot.wait_until_ready()

if __name__ == "__main__":
    bot.run(DISCORD_BOT_TOKEN)
