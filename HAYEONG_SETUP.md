# ============================================================
#  HAYEONG SETUP GUIDE
# ============================================================

# ---- 1. .env file (create this in your project folder) ----

DISCORD_TOKEN=your_discord_bot_token_here
OWNER_DISCORD_ID=your_discord_user_id_here   # right-click yourself in Discord > Copy ID (need Developer Mode on)

# ============================================================
#  PYTHON DEPENDENCIES
# ============================================================
#
# pip install discord.py python-dotenv gtts pyttsx3 faster-whisper
#             scipy sounddevice numpy requests
#
# For a much better voice (optional upgrade):
#   pip install TTS playsound

# ============================================================
#  DISCORD BOT SETUP (if you haven't already)
# ============================================================
#
# 1. Go to https://discord.com/developers/applications
# 2. New Application → name it "Hayeong"
# 3. Bot tab → Add Bot → copy the TOKEN into your .env
# 4. Under "Privileged Gateway Intents" turn ON:
#      - Message Content Intent
#      - Server Members Intent
# 5. OAuth2 → URL Generator:
#      Scopes: bot
#      Permissions: Send Messages, Read Messages, Connect, Speak
# 6. Paste the generated URL in your browser to invite her to your server
# 7. In your Discord server, create a text channel called: hayeong-chat
#    (She will ONLY respond there — change ALLOWED_TEXT_CHANNELS in discord_hayeong.py if you want)
# 8. Make sure FFmpeg is installed:
#      Windows: https://ffmpeg.org/download.html → add to PATH
#      OR: pip install ffmpeg-python  (fallback)
#
# Run: python discord_hayeong.py

# ============================================================
#  VOICE IMPROVEMENTS
# ============================================================
#
# Current: pyttsx3 (robot voice, but functional)
#   - voice.py now auto-picks the best female voice on your system
#   - On Windows, install additional SAPI5 voices for better options
#     Settings → Time & Language → Speech → Add voices
#
# UPGRADE — Coqui TTS (free, sounds MUCH better, runs locally):
#   pip install TTS playsound
#   Then follow the comment block in voice.py (UPGRADE PATH section)
#   Recommended model: tts_models/en/vctk/vits with speaker p264

# ============================================================
#  MINECRAFT SETUP
# ============================================================
#
# Requirements:
#   - Node.js 18+ installed (https://nodejs.org)
#   - Your Minecraft server running (can be local via Aternos/LAN/etc)
#   - Server must allow the bot username to connect
#     (For offline/local servers set online-mode=false in server.properties)
#
# 1. In your project folder, init Node and install Mineflayer:
#      npm init -y
#      npm install mineflayer mineflayer-pathfinder
#
# 2. Edit hayeong_bot.js — set these at the top:
#      MC_HOST    → your server IP (or "localhost")
#      MC_PORT    → your server port (default 25565)
#      MC_VERSION → match your server exactly (e.g. "1.20.1")
#
# 3. Start in this order:
#      Terminal 1:  python minecraft_bridge.py
#      Terminal 2:  node hayeong_bot.js
#
# 4. Join your Minecraft server — Hayeong will spawn and follow you
#    Type in MC chat to talk to her, she'll respond and try to help

# ============================================================
#  RUNNING EVERYTHING TOGETHER
# ============================================================
#
# Terminal 1: python discord_hayeong.py     (Discord)
# Terminal 2: python minecraft_bridge.py   (Minecraft brain)
# Terminal 3: node hayeong_bot.js          (Minecraft body)
# (Optional) Terminal 4: python main.py   (Local voice mode)
#
# All three can run at the same time — she'll be in both Discord AND Minecraft

# ============================================================
#  COMMANDS IN DISCORD (in #hayeong-chat)
# ============================================================
#
# Just chat normally — she reads everything and responds
# !mood              → see her current mood state
# !trait key=value   → adjust a personality trait on the fly
#                      e.g. !trait teasing_level=low
# !exit              → gracefully shut her down

# ============================================================
#  FUTURE PLANS (when you're ready)
# ============================================================
#
# [ ] Better memory: replace memory.json with a vector DB (ChromaDB)
#     so she can actually remember things from months ago intelligently
# [ ] Minecraft learning: log what works/doesn't and fine-tune her
#     decision making over time
# [ ] Her own PC: when you build it, just move all files over,
#     install Ollama + same dependencies, and she'll run there instead
# [ ] Other games: the Python bridge pattern works for any game
#     that has a bot API (e.g. Among Us, various MMOs, etc.)
