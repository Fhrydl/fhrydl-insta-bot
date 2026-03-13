import os
import logging
import tempfile
import re
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import yt_dlp
import requests

# ================= KONFIGURASI =================
TOKEN = "8646575981:AAFxPaVmIGJnPd2FzlfCTbUaMQQ4oPGcyUg"
CHANNEL_USERNAME = "@FahArchives"  # atau "@FahArchives"
CHANNEL_LINK = "https://t.me/FahArchives"

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================= CEK MEMBER CHANNEL =================
async def is_user_member(bot, user_id: int) -> bool:
    """Cek apakah user sudah join channel"""
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Error cek member: {e}")
        return False

# ================= HANDLER START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if await is_user_member(context.bot, user.id):
        await update.message.reply_text(
            "👋 Halo! Kirimkan link Instagram (postingan, reels, story, atau profil) untuk di download.\n\n"
            "Contoh:\n"
            "• https://www.instagram.com/p/xxxx/\n"
            "• https://www.instagram.com/reel/xxxx/\n"
            "• https://www.instagram.com/stories/username/xxxx/\n"
            "• https://www.instagram.com/username/"
        )
    else:
        keyboard = [[InlineKeyboardButton("🔹 Join Channel", url=CHANNEL_LINK)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "🚫 Anda harus join channel kami terlebih dahulu untuk menggunakan bot ini.",
            reply_markup=reply_markup
        )

# ================= HANDLER PESAN =================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    # Cek keanggotaan channel
    if not await is_user_member(context.bot, user.id):
        keyboard = [[InlineKeyboardButton("🔹 Join Channel", url=CHANNEL_LINK)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "🚫 Akses ditolak. Anda harus join channel terlebih dahulu.",
            reply_markup=reply_markup
        )
        return

    text = update.message.text.strip()
    # Validasi apakah itu link Instagram
    insta_pattern = r'(https?://(?:www\.)?instagram\.com/(?:p|reel|stories|tv|([A-Za-z0-9._]+))/?)'
    if not re.match(insta_pattern, text):
        await update.message.reply_text("❌ Harap kirim link Instagram yang valid.")
        return

    # Proses download
    await update.message.reply_text("⏬ Mendownload... mohon tunggu.")
    try:
        await download_and_send_instagram(update, context, text)
    except Exception as e:
        logger.error(f"Error download: {e}")
        await update.message.reply_text(f"❌ Gagal mendownload: {str(e)[:100]}")

# ================= FUNGSI DOWNLOAD =================
async def download_and_send_instagram(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    """Download media dari Instagram menggunakan yt-dlp dan kirim ke user"""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'outtmpl': str(Path(tempfile.gettempdir()) / '%(title).50s.%(ext)s'),  # simpan di /tmp
        'restrictfilenames': True,
        'noplaylist': False,  # untuk handle multiple items (carousel)
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if 'entries' in info:  # Untuk carousel / playlist
                for entry in info['entries']:
                    if entry:
                        file_path = ydl.prepare_filename(entry)
                        await send_media(update, context, file_path, entry)
            else:
                file_path = ydl.prepare_filename(info)
                await send_media(update, context, file_path, info)
    except Exception as e:
        raise Exception(f"yt-dlp error: {e}")

async def send_media(update: Update, context: ContextTypes.DEFAULT_TYPE, file_path: str, info: dict):
    """Kirim file ke user berdasarkan tipe"""
    if not os.path.exists(file_path):
        # Coba cari file dengan ekstensi lain (yt-dlp kadang ubah ekstensi)
        base = Path(file_path).stem
        for f in Path(tempfile.gettempdir()).glob(f"{base}.*"):
            file_path = str(f)
            break
        else:
            await update.message.reply_text("⚠️ File tidak ditemukan.")
            return

    try:
        # Tentukan tipe dari info
        ext = Path(file_path).suffix.lower()
        if info.get('_type') == 'video' or ext in ['.mp4', '.mov', '.webm']:
            with open(file_path, 'rb') as f:
                await update.message.reply_video(f, caption="✅ Video berhasil didownload")
        elif ext in ['.jpg', '.jpeg', '.png', '.webp']:
            with open(file_path, 'rb') as f:
                await update.message.reply_photo(f, caption="✅ Foto berhasil didownload")
        else:
            # Fallback kirim sebagai dokumen
            with open(file_path, 'rb') as f:
                await update.message.reply_document(f, caption="✅ File berhasil didownload")
    finally:
        # Hapus file setelah dikirim
        try:
            os.remove(file_path)
        except:
            pass

# ================= HANDLER FOTO PROFIL (KHUSUS) =================
# Untuk foto profil, kita tangani secara terpisah jika link adalah profil
async def handle_profile(update: Update, context: ContextTypes.DEFAULT_TYPE, username: str):
    """Download foto profil Instagram"""
    # Metode sederhana: ambil dari halaman web
    url = f"https://www.instagram.com/{username}/"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            # Cari gambar profil dari meta tag
            import re
            og_image = re.search(r'<meta property="og:image" content="([^"]+)"', response.text)
            if og_image:
                profile_pic_url = og_image.group(1)
                # Download gambar
                img_response = requests.get(profile_pic_url, headers=headers)
                if img_response.status_code == 200:
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp:
                        tmp.write(img_response.content)
                        tmp_path = tmp.name
                    with open(tmp_path, 'rb') as f:
                        await update.message.reply_photo(f, caption=f"✅ Foto profil @{username}")
                    os.remove(tmp_path)
                    return
        raise Exception("Tidak dapat mengambil foto profil")
    except Exception as e:
        await update.message.reply_text(f"❌ Gagal mengambil foto profil: {e}")

# ================= MAIN =================
def main() -> None:
    # Buat aplikasi
    application = Application.builder().token(TOKEN).build()

    # Handler
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Jalankan webhook (untuk production di Vercel)
    # Kita akan jalankan via serverless, jadi perlu konfigurasi
    # Set webhook secara manual (lihat README)

    # Untuk development (polling) bisa dijalankan dengan:
    # application.run_polling()

# ================= UNTUK VERCEl (serverless) =================
from flask import Flask, request
import asyncio

app = Flask(__name__)

# Inisialisasi bot di global
application = None

@app.before_first_request
def init_bot():
    global application
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

@app.route('/', methods=['POST'])
def webhook():
    """Terima update dari Telegram"""
    if application is None:
        init_bot()
    # Proses update
    update = Update.de_json(request.get_json(force=True), application.bot)
    asyncio.run(application.process_update(update))
    return 'ok', 200

@app.route('/set_webhook', methods=['GET'])
def set_webhook():
    """Endpoint untuk set webhook (panggil sekali setelah deploy)"""
    # Dapatkan URL dari request (sesuaikan dengan domain Vercel)
    url = request.url_root.rstrip('/') + '/'
    ok = application.bot.set_webhook(url=url)
    return f"Webhook set: {ok}", 200 if ok else 400

if __name__ == '__main__':
    # Untuk local test, jalankan flask
    app.run()
