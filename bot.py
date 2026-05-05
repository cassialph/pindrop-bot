import os, json, base64, time, re
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes

# ── CONFIG ────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ['TELEGRAM_TOKEN']
GEMINI_KEY     = os.environ['GEMINI_KEY']
AT_TOKEN       = os.environ['AT_TOKEN']
AT_BASE        = os.environ['AT_BASE']
AT_TABLE       = os.environ['AT_TABLE']

GEMINI_URL = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_KEY}'
AT_URL     = f'https://api.airtable.com/v0/{AT_BASE}/{AT_TABLE}'
AT_HEADERS = {'Authorization': f'Bearer {AT_TOKEN}', 'Content-Type': 'application/json'}

CATEGORIES = ['restaurant', 'cafe', 'attraction', 'hotel', 'shop', 'bar', 'other']

# ── AIRTABLE ──────────────────────────────────────────────
def save_to_airtable(place: dict) -> str:
    fields = {
        'Name':         place.get('name', ''),
        'City':         place.get('city', ''),
        'Country':      place.get('country', ''),
        'Address':      place.get('address', ''),
        'Category':     place.get('category', 'other'),
        'Notes':        place.get('notes', ''),
        'Source URL':   place.get('sourceUrl', ''),
        'Visited':      False,
        'AI Extracted': True,
    }
    res = requests.post(AT_URL, headers=AT_HEADERS, json={'fields': fields})
    res.raise_for_status()
    return res.json()['id']

# ── GEMINI ────────────────────────────────────────────────
def extract_place(image_b64: str, mime: str) -> dict:
    prompt = """You are analyzing an image that may be a screenshot from Instagram, a blog, a travel site, or a photo of a place.

Extract information about the specific place shown and return ONLY a valid JSON object:

{
  "name": "name of the place",
  "city": "city",
  "country": "country",
  "address": "street address if visible, else empty string",
  "category": "restaurant" or "cafe" or "attraction" or "hotel" or "shop" or "bar" or "other",
  "notes": "2-3 sentences: what makes it special, must-try items, atmosphere"
}

Return ONLY the JSON object, no markdown."""

    body = {
        'contents': [{'parts': [
            {'text': prompt},
            {'inlineData': {'mimeType': mime, 'data': image_b64}}
        ]}],
        'generationConfig': {'temperature': 0.1}
    }

    for attempt in range(3):
        res = requests.post(GEMINI_URL, json=body)
        if res.ok:
            break
        if attempt < 2:
            time.sleep(4)

    res.raise_for_status()
    raw = res.json()['candidates'][0]['content']['parts'][0]['text']
    cleaned = re.sub(r'```json\n?|```\n?', '', raw).strip()
    return json.loads(cleaned)

# ── HANDLERS ──────────────────────────────────────────────
async def handle_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hi! I'm your PinDrop assistant.\n\n"
        "Send me a screenshot from Instagram, TikTok, or anywhere — "
        "I'll extract the place info and save it to your PinDrop map automatically.\n\n"
        "Just send a photo to get started!"
    )

async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    await msg.reply_text("📸 Got it! Reading the image...")

    # Download the image from Telegram
    photo = msg.photo[-1]  # largest size
    file = await ctx.bot.get_file(photo.file_id)
    img_bytes = bytes(await file.download_as_bytearray())
    img_b64 = base64.b64encode(img_bytes).decode()

    try:
        await msg.reply_text("✨ Extracting place info with AI...")
        place = extract_place(img_b64, 'image/jpeg')

        await msg.reply_text("💾 Saving to your PinDrop map...")
        rec_id = save_to_airtable(place)

        cat_icons = {'restaurant':'🍽','cafe':'☕','attraction':'🏛','hotel':'🏨','shop':'🛍','bar':'🍺','other':'📍'}
        icon = cat_icons.get(place.get('category','other'), '📍')
        location = ', '.join(filter(None, [place.get('city'), place.get('country')]))

        await msg.reply_text(
            f"✅ Saved to PinDrop!\n\n"
            f"{icon} *{place.get('name', 'Unknown')}*\n"
            f"📍 {location}\n"
            f"🏠 {place.get('address','')}\n\n"
            f"{place.get('notes','')}\n\n"
            f"_Open PinDrop to see it on the map._",
            parse_mode='Markdown'
        )

    except Exception as e:
        print(f'Error: {e}')
        await msg.reply_text(f"❌ Something went wrong: {str(e)}\n\nTry sending a clearer screenshot.")

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send me a photo/screenshot and I'll save the place to PinDrop! 📸"
    )

# ── MAIN ──────────────────────────────────────────────────
if __name__ == '__main__':
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler('start', handle_start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print('PinDrop bot is running...')
    app.run_polling()
