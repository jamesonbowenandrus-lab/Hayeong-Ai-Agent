// discord_hayeong.js
// Hayeong's Discord presence — built on discord.js which has full DAVE/E2EE support.
// Replaces discord_hayeong.py which broke when Discord enforced DAVE on March 2, 2026.
//
// ARCHITECTURE:
//   This JS bot handles everything Discord-specific:
//     - DAVE/E2EE voice (handled transparently by @discordjs/voice)
//     - Joining/leaving voice channels
//     - Text chat in allowed channels
//     - TTS playback (speaks Hayeong's responses in voice channel)
//     - Voice receive → WAV file → sent to Python for Whisper transcription
//
//   Python bridge (port 9877) handles everything AI-specific:
//     - Whisper transcription of audio
//     - Ollama AI response generation
//     - F5-TTS audio generation
//     - Memory, mood, energy
//
//   Communication: JSON over TCP socket (same pattern as Minecraft bridge)
//     JS → Python: { type: "text_message"|"voice_audio_file"|"ready", ... }
//     Python → JS: { type: "speak"|"text_reply"|"status", ... }
//
// INSTALL:
//   npm install discord.js @discordjs/voice @discordjs/opus ffmpeg-static sodium-native
//   node discord_hayeong.js
//
// .env entries needed (same file Hayeong already uses):
//   DISCORD_TOKEN=your_bot_token
//   OWNER_DISCORD_ID=your_discord_user_id
//   ALLOWED_TEXT_CHANNEL=hayeong-chat

"use strict";

const fs      = require("fs");
const path    = require("path");
const net     = require("net");
const { execFile } = require("child_process");

const {
    Client,
    GatewayIntentBits,
    Events,
} = require("discord.js");

const {
    joinVoiceChannel,
    createAudioPlayer,
    createAudioResource,
    AudioPlayerStatus,
    VoiceConnectionStatus,
    entersState,
    EndBehaviorType,
    getVoiceConnection,
} = require("@discordjs/voice");

// ─────────────────────────────────────────────
// CONFIG
// ─────────────────────────────────────────────

// Load .env manually (dotenv may not be installed in node env)
function loadEnv() {
    const envPath = path.join(__dirname, ".env");
    if (!fs.existsSync(envPath)) return;
    const lines = fs.readFileSync(envPath, "utf8").split("\n");
    for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith("#")) continue;
        const idx = trimmed.indexOf("=");
        if (idx < 0) continue;
        const key = trimmed.slice(0, idx).trim();
        const val = trimmed.slice(idx + 1).trim().replace(/^['"]|['"]$/g, "");
        if (!process.env[key]) process.env[key] = val;
    }
}
loadEnv();

const TOKEN               = process.env.DISCORD_TOKEN;
const OWNER_ID            = process.env.OWNER_DISCORD_ID || "0";
const ALLOWED_CHANNEL     = process.env.ALLOWED_TEXT_CHANNEL || "hayeong-chat";
const BRIDGE_PORT         = 9877;   // Python bridge port (9876 = Minecraft, 9877 = Discord)
const BRIDGE_HOST         = "127.0.0.1";
const TMP_DIR             = path.join(__dirname, "tmp_audio");
const SILENCE_THRESHOLD   = 0.003;  // RMS below this is treated as silence
const MIN_AUDIO_SECONDS   = 0.8;    // Ignore clips shorter than this

if (!TOKEN) {
    console.error("❌ DISCORD_TOKEN not set in .env");
    process.exit(1);
}

if (!fs.existsSync(TMP_DIR)) fs.mkdirSync(TMP_DIR, { recursive: true });


// ─────────────────────────────────────────────
// PYTHON BRIDGE
// JSON over TCP — same pattern as Minecraft bot.
// Python handles Whisper, Ollama, F5-TTS.
// ─────────────────────────────────────────────

let bridge       = null;
let bridgeReady  = false;
let bridgeBuffer = "";
let reconnTimer  = null;

function connectBridge() {
    if (reconnTimer) clearTimeout(reconnTimer);
    bridge = new net.Socket();

    bridge.connect(BRIDGE_PORT, BRIDGE_HOST, () => {
        console.log("🐍 Python bridge connected");
        bridgeReady = true;
        sendToBridge({ type: "ready", source: "discord_js" });
    });

    bridge.on("data", (data) => {
        bridgeBuffer += data.toString();
        while (bridgeBuffer.includes("\n")) {
            const idx  = bridgeBuffer.indexOf("\n");
            const line = bridgeBuffer.slice(0, idx).trim();
            bridgeBuffer = bridgeBuffer.slice(idx + 1);
            if (!line) continue;
            try {
                handleBridgeMessage(JSON.parse(line));
            } catch (e) {
                console.error("⚠️  Bad JSON from bridge:", line.slice(0, 80));
            }
        }
    });

    bridge.on("close", () => {
        bridgeReady = false;
        console.log("🔴 Bridge disconnected — retry in 5s");
        reconnTimer = setTimeout(connectBridge, 5000);
    });

    bridge.on("error", (e) => {
        // suppress ECONNREFUSED spam — Python side may not be ready yet
        if (e.code !== "ECONNREFUSED") console.error("Bridge error:", e.message);
    });
}

function sendToBridge(obj) {
    if (!bridgeReady || !bridge) return;
    try {
        bridge.write(JSON.stringify(obj) + "\n");
    } catch (e) {}
}


// ─────────────────────────────────────────────
// HANDLE MESSAGES FROM PYTHON
// Python sends back responses to deliver to Discord.
// ─────────────────────────────────────────────

function handleBridgeMessage(msg) {
    const { type } = msg;

    if (type === "speak") {
        // Python generated a TTS audio file — play it in voice channel
        const filePath = msg.file_path;
        if (filePath && fs.existsSync(filePath)) {
            playAudioFile(filePath);
        }
    }

    if (type === "text_reply") {
        // Send text response to the active text channel
        if (activeTextChannel && msg.text) {
            // Prefix voice replies with the mic emoji so it's clear
            const prefix = msg.source === "voice" ? "*[🎙️]* " : "";
            const chunks = chunkText(msg.text, 1900);
            (async () => {
                for (const chunk of chunks) {
                    await activeTextChannel.send(prefix + chunk);
                }
            })().catch(console.error);
        }
    }

    if (type === "status") {
        console.log(`[Bridge] ${msg.message || JSON.stringify(msg)}`);
    }
}


// ─────────────────────────────────────────────
// DISCORD CLIENT
// ─────────────────────────────────────────────

const client = new Client({
    intents: [
        GatewayIntentBits.Guilds,
        GatewayIntentBits.GuildMessages,
        GatewayIntentBits.GuildVoiceStates,
        GatewayIntentBits.MessageContent,
        GatewayIntentBits.DirectMessages,
    ],
});

let activeTextChannel = null;
let audioPlayer       = createAudioPlayer();
let isPlaying         = false;
const audioQueue      = [];


// ─────────────────────────────────────────────
// AUDIO PLAYER
// Queues TTS files and plays them in order.
// ─────────────────────────────────────────────

audioPlayer.on(AudioPlayerStatus.Idle, () => {
    isPlaying = false;
    playNext();
});

audioPlayer.on("error", (e) => {
    console.error("⚠️  Audio player error:", e.message);
    isPlaying = false;
    playNext();
});

function playNext() {
    if (isPlaying || audioQueue.length === 0) return;
    const filePath = audioQueue.shift();
    if (!fs.existsSync(filePath)) { playNext(); return; }

    try {
        const resource = createAudioResource(filePath);
        audioPlayer.play(resource);
        isPlaying = true;
        console.log(`🔊 Playing: ${path.basename(filePath)}`);

        // Clean up file after a delay
        setTimeout(() => {
            try { fs.unlinkSync(filePath); } catch (e) {}
        }, 30000);
    } catch (e) {
        console.error("⚠️  Failed to play audio:", e.message);
        isPlaying = false;
        playNext();
    }
}

function playAudioFile(filePath) {
    audioQueue.push(filePath);
    playNext();
}


// ─────────────────────────────────────────────
// VOICE CONNECTION
// ─────────────────────────────────────────────

async function joinVoice(channel) {
    try {
        const connection = joinVoiceChannel({
            channelId:      channel.id,
            guildId:        channel.guild.id,
            adapterCreator: channel.guild.voiceAdapterCreator,
            selfDeaf:       false,
            selfMute:       false,
        });

        // Subscribe audio player to the connection
        connection.subscribe(audioPlayer);

        // Wait for connection to be ready
        await entersState(connection, VoiceConnectionStatus.Ready, 20_000);
        console.log(`✅ Joined voice: ${channel.name}`);

        // Start listening for audio
        startListening(connection, channel.guild.id);

        return connection;
    } catch (e) {
        console.error(`⚠️  Failed to join voice: ${e.message}`);
        return null;
    }
}

function leaveVoice(guildId) {
    const connection = getVoiceConnection(guildId);
    if (connection) {
        connection.destroy();
        console.log("🔇 Left voice channel");
    }
}


// ─────────────────────────────────────────────
// VOICE RECEIVE
// Records user audio, checks RMS, sends to Python for Whisper.
// This is the temporary local bridge approach — Python handles
// transcription via its existing faster-whisper setup.
// When @discordjs/voice fixes DAVE receive, this section can be
// upgraded to use the proper Discord audio receive pipeline.
// ─────────────────────────────────────────────

const listeningUsers = new Map(); // userId → { chunks, timeout }

function startListening(connection, guildId) {
    const receiver = connection.receiver;

    receiver.speaking.on("start", (userId) => {
        if (userId === client.user?.id) return;
        if (userId !== OWNER_ID) return; // Only listen to James for now

        console.log(`🎙️  James started speaking`);

        if (!listeningUsers.has(userId)) {
            listeningUsers.set(userId, { chunks: [], timeout: null });
        }

        const userData = listeningUsers.get(userId);
        if (userData.timeout) clearTimeout(userData.timeout);

        // Subscribe to audio stream for this user
        try {
            const audioStream = receiver.subscribe(userId, {
                end: {
                    behavior: EndBehaviorType.AfterSilence,
                    duration: 1000, // 1s of silence ends the stream
                },
            });

            audioStream.on("data", (chunk) => {
                userData.chunks.push(chunk);
            });

            audioStream.on("end", async () => {
                const chunks = userData.chunks.splice(0);
                listeningUsers.delete(userId);

                if (chunks.length === 0) return;

                // Combine all PCM chunks
                const pcmBuffer = Buffer.concat(chunks);

                // Basic RMS check — skip silence
                const samples = new Int16Array(pcmBuffer.buffer, pcmBuffer.byteOffset, pcmBuffer.length / 2);
                let sumSq = 0;
                for (const s of samples) sumSq += (s / 32768) ** 2;
                const rms = Math.sqrt(sumSq / samples.length);

                console.log(`   [rms=${rms.toFixed(4)}]`);
                if (rms < SILENCE_THRESHOLD) {
                    console.log("   (silence — skipping)");
                    return;
                }

                // Check minimum duration (48000 Hz stereo 16-bit = 192000 bytes/sec)
                const durationSecs = pcmBuffer.length / 192000;
                if (durationSecs < MIN_AUDIO_SECONDS) {
                    console.log(`   (too short: ${durationSecs.toFixed(2)}s — skipping)`);
                    return;
                }

                console.log(`   [voice detected — ${durationSecs.toFixed(1)}s — sending to Python]`);

                // Save as WAV file for Python/Whisper
                const wavPath = path.join(TMP_DIR, `voice_${Date.now()}.wav`);
                writeWav(wavPath, pcmBuffer, 48000, 2);

                // Send file path to Python bridge for transcription + response
                sendToBridge({
                    type:      "voice_audio_file",
                    file_path: wavPath,
                    user_id:   userId,
                    duration:  durationSecs,
                });
            });

        } catch (e) {
            console.error("⚠️  Subscribe error:", e.message);
        }
    });

    console.log(`👂 Listening in voice (owner ID: ${OWNER_ID})`);
}


// ─────────────────────────────────────────────
// WAV WRITER
// Writes raw PCM to a proper WAV file Python/Whisper can read.
// Discord sends 48kHz stereo 16-bit signed PCM (Opus decoded).
// ─────────────────────────────────────────────

function writeWav(filePath, pcmBuffer, sampleRate, channels) {
    const bitsPerSample  = 16;
    const byteRate       = sampleRate * channels * (bitsPerSample / 8);
    const blockAlign     = channels * (bitsPerSample / 8);
    const dataSize       = pcmBuffer.length;
    const headerSize     = 44;
    const fileSize       = headerSize + dataSize;

    const buf = Buffer.alloc(fileSize);
    let offset = 0;

    // RIFF header
    buf.write("RIFF", offset);          offset += 4;
    buf.writeUInt32LE(fileSize - 8, offset); offset += 4;
    buf.write("WAVE", offset);          offset += 4;

    // fmt chunk
    buf.write("fmt ", offset);          offset += 4;
    buf.writeUInt32LE(16, offset);      offset += 4; // chunk size
    buf.writeUInt16LE(1, offset);       offset += 2; // PCM format
    buf.writeUInt16LE(channels, offset);offset += 2;
    buf.writeUInt32LE(sampleRate, offset); offset += 4;
    buf.writeUInt32LE(byteRate, offset);   offset += 4;
    buf.writeUInt16LE(blockAlign, offset); offset += 2;
    buf.writeUInt16LE(bitsPerSample, offset); offset += 2;

    // data chunk
    buf.write("data", offset);          offset += 4;
    buf.writeUInt32LE(dataSize, offset);   offset += 4;
    pcmBuffer.copy(buf, offset);

    fs.writeFileSync(filePath, buf);
}


// ─────────────────────────────────────────────
// TEXT HELPERS
// ─────────────────────────────────────────────

function chunkText(text, maxLen) {
    const chunks = [];
    while (text.length > maxLen) {
        let splitAt = text.lastIndexOf("\n", maxLen);
        if (splitAt < 0) splitAt = maxLen;
        chunks.push(text.slice(0, splitAt));
        text = text.slice(splitAt).trimStart();
    }
    if (text) chunks.push(text);
    return chunks;
}


// ─────────────────────────────────────────────
// DISCORD EVENTS
// ─────────────────────────────────────────────

client.once(Events.ClientReady, async (c) => {
    console.log(`\n✅ Hayeong online as ${c.user.tag}`);
    console.log(`👤 Owner ID: ${OWNER_ID || "❌ NOT SET — add OWNER_DISCORD_ID to .env"}`);
    console.log(`💬 Allowed text channel: ${ALLOWED_CHANNEL}`);
    console.log(`🔊 DAVE/E2EE: handled by @discordjs/voice ✅`);
    console.log(`🎙️  Voice receive: local WAV bridge → Python Whisper\n`);

    // Find active text channel
    for (const guild of c.guilds.cache.values()) {
        for (const ch of guild.channels.cache.values()) {
            if (ch.isTextBased() && ch.name === ALLOWED_CHANNEL) {
                activeTextChannel = ch;
                break;
            }
        }

        // Auto-join if owner is already in a voice channel
        if (OWNER_ID && OWNER_ID !== "0") {
            const owner = guild.members.cache.get(OWNER_ID);
            if (owner?.voice?.channel) {
                console.log(`🎙️  Owner already in voice — joining: ${owner.voice.channel.name}`);
                await joinVoice(owner.voice.channel);
            }
        }
    }

    // Connect to Python bridge
    connectBridge();
});


// Auto-join/leave when owner moves between voice channels
client.on(Events.VoiceStateUpdate, async (oldState, newState) => {
    if (newState.member?.id !== OWNER_ID) return;

    const guildId = newState.guild.id;

    if (newState.channel && newState.channel !== oldState.channel) {
        // Owner joined or moved to a voice channel
        const existing = getVoiceConnection(guildId);
        if (existing) existing.destroy();
        console.log(`🎙️  Owner moved to: ${newState.channel.name} — following`);
        await joinVoice(newState.channel);
    } else if (!newState.channel && oldState.channel) {
        // Owner left voice
        leaveVoice(guildId);
    }
});


// Text chat handler
client.on(Events.MessageCreate, async (message) => {
    if (message.author.bot) return;
    if (!message.guild) return; // ignore DMs for now
    if (message.channel.name !== ALLOWED_CHANNEL) return;
    if (message.author.id !== OWNER_ID) return; // Only James for now

    activeTextChannel = message.channel;
    const text = message.content.trim();
    if (!text) return;

    // ── Bot commands ──
    if (text.toLowerCase() === "!join") {
        const voiceChannel = message.member?.voice?.channel;
        if (voiceChannel) {
            const existing = getVoiceConnection(message.guild.id);
            if (existing) existing.destroy();
            await joinVoice(voiceChannel);
            await message.channel.send(`🎙️ Joined **${voiceChannel.name}**`);
        } else {
            await message.channel.send("Join a voice channel first, then type `!join`.");
        }
        return;
    }

    if (text.toLowerCase() === "!leave") {
        leaveVoice(message.guild.id);
        await message.channel.send("👋 Left voice.");
        return;
    }

    if (text.toLowerCase() === "!status") {
        const vc = getVoiceConnection(message.guild.id);
        await message.channel.send(
            `**Status**\n` +
            `Voice: ${vc ? "Connected ✅" : "Not connected"}\n` +
            `Bridge: ${bridgeReady ? "Python connected ✅" : "Python disconnected ⚠️"}\n` +
            `Audio queue: ${audioQueue.length} item(s)`
        );
        return;
    }

    // ── Main AI response ──
    // Send to Python bridge — it handles AI + TTS + response
    console.log(`💬 [${message.author.username}]: ${text.slice(0, 80)}`);
    sendToBridge({
        type:    "text_message",
        text:    text,
        user_id: message.author.id,
        source:  "discord_text",
    });

    // Show typing indicator while Python processes
    message.channel.sendTyping().catch(() => {});
});


// ─────────────────────────────────────────────
// START
// ─────────────────────────────────────────────

client.login(TOKEN).catch((e) => {
    console.error("❌ Login failed:", e.message);
    process.exit(1);
});

process.on("SIGINT", async () => {
    console.log("\n🛑 Shutting down...");
    sendToBridge({ type: "shutdown" });
    for (const guild of client.guilds.cache.values()) {
        leaveVoice(guild.id);
    }
    await client.destroy();
    process.exit(0);
});
