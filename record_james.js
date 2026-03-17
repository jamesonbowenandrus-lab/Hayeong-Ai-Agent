// record_james.js
// Connects to your server as a silent observer and logs James's actions.
// Run this separately when you want to record a session for training data.
//
// Usage:
//   node record_james.js
//
// Creates: logs/james_YYYY-MM-DD_HH-MM.jsonl
// Each line = one snapshot: game state + what James did next

const mineflayer = require("mineflayer");
const fs         = require("fs");
const path       = require("path");

// -------------------------
// Config
// -------------------------
const MC_HOST     = "localhost";
const MC_PORT     = 25565;
const MC_VERSION  = "1.21.11";
const JAMES_NAME  = "hiplizard36";   // James's Minecraft username
const SAMPLE_RATE = 2000;            // snapshot every 2 seconds

// -------------------------
// Log file setup
// -------------------------
const logDir = path.join(__dirname, "logs");
if (!fs.existsSync(logDir)) fs.mkdirSync(logDir);

const now      = new Date();
const dateStr  = now.toISOString().slice(0,10);
const timeStr  = now.toTimeString().slice(0,5).replace(":", "-");
const logFile  = path.join(logDir, `james_${dateStr}_${timeStr}.jsonl`);

console.log(`📹 Recording to: ${logFile}`);
console.log(`   Watching: ${JAMES_NAME}`);
console.log(`   Press Ctrl+C to stop\n`);

// -------------------------
// Observer bot (invisible, just watches)
// -------------------------
const observer = mineflayer.createBot({
    host:     MC_HOST,
    port:     MC_PORT,
    username: "Hayeong_Observer",
    version:  MC_VERSION,
});

let lastJamesState = null;
let sessionLabel   = "general";  // tag for what activity is being recorded
let frameCount     = 0;

function getJamesState() {
    const james = observer.players[JAMES_NAME];
    if (!james || !james.entity) return null;

    const pos = james.entity.position;

    // What is James holding?
    const heldItem = james.entity.heldItem?.name || "nothing";

    // What blocks are around James?
    const nearbyBlocks = [];
    for (let dx = -3; dx <= 3; dx++) {
        for (let dy = -2; dy <= 2; dy++) {
            for (let dz = -3; dz <= 3; dz++) {
                try {
                    const block = observer.blockAt(pos.offset(dx, dy, dz));
                    if (block && block.name !== "air" && block.name !== "grass_block"
                        && block.name !== "dirt" && block.name !== "stone") {
                        nearbyBlocks.push(block.name);
                    }
                } catch(e) {}
            }
        }
    }
    const uniqueBlocks = [...new Set(nearbyBlocks)].slice(0, 10);

    // Nearby entities
    const nearbyEntities = Object.values(observer.entities)
        .filter(e => e.username !== JAMES_NAME && e.username !== "Hayeong_Observer"
                  && e.position?.distanceTo(pos) < 10)
        .slice(0, 5)
        .map(e => ({ type: e.type, name: e.name || e.username, dist: Math.round(e.position.distanceTo(pos)) }));

    return {
        position:       { x: Math.round(pos.x), y: Math.round(pos.y), z: Math.round(pos.z) },
        held_item:      heldItem,
        nearby_blocks:  uniqueBlocks,
        nearby_entities: nearbyEntities,
        time_of_day:    observer.time?.timeOfDay ?? null,
        is_raining:     observer.isRaining ?? false,
    };
}

function logFrame(eventType, extra = {}) {
    const state = getJamesState();
    if (!state) return;

    const entry = {
        timestamp:   new Date().toISOString(),
        session:     sessionLabel,
        frame:       frameCount++,
        event:       eventType,
        james_state: state,
        extra,
        // This is where you'll label the "correct" action later for training
        // Leave as null during recording — fill in during review
        correct_action: null,
        notes: null,
    };

    fs.appendFileSync(logFile, JSON.stringify(entry) + "\n");
    process.stdout.write(`\r📹 Frame ${frameCount} | ${eventType.padEnd(12)} | held: ${state.held_item.padEnd(20)} | blocks: ${state.nearby_blocks.slice(0,3).join(",")}    `);
}

// -------------------------
// Snapshot loop — periodic state capture
// -------------------------
let snapshotInterval = null;

function startRecording() {
    snapshotInterval = setInterval(() => {
        logFrame("snapshot");
        lastJamesState = getJamesState();
    }, SAMPLE_RATE);
}

// -------------------------
// Event-triggered logs — capture important moments
// -------------------------
observer.on("playerCollect", (collector, collected) => {
    if (collector.username === JAMES_NAME) {
        logFrame("picked_up", { item: collected.objectType?.name });
    }
});

observer.on("chat", (username, message) => {
    if (username === JAMES_NAME) {
        logFrame("james_chat", { message });
    }
    // Listen for label commands from James in chat
    // Type "label mining" in game to tag the session
    if (username === JAMES_NAME && message.startsWith("label ")) {
        sessionLabel = message.slice(6).trim();
        console.log(`\n🏷️  Session labeled: "${sessionLabel}"`);
        observer.chat(`Recording labeled: ${sessionLabel}`);
    }
    if (username === JAMES_NAME && message === "record stop") {
        console.log(`\n✅ Recording stopped. ${frameCount} frames saved to ${logFile}`);
        process.exit(0);
    }
});

// -------------------------
// Movement detection — log when James moves significantly
// -------------------------
setInterval(() => {
    const current = getJamesState();
    if (!current || !lastJamesState) { lastJamesState = current; return; }

    const dx = Math.abs(current.position.x - lastJamesState.position.x);
    const dz = Math.abs(current.position.z - lastJamesState.position.z);
    const moved = Math.sqrt(dx*dx + dz*dz);

    if (moved > 3) {
        logFrame("moved", { distance: Math.round(moved) });
    }

    // Detect tool change
    if (current.held_item !== lastJamesState.held_item) {
        logFrame("switched_item", {
            from: lastJamesState.held_item,
            to:   current.held_item
        });
    }

    lastJamesState = current;
}, 1000);

// -------------------------
// Bot events
// -------------------------
observer.on("spawn", () => {
    console.log("✅ Observer spawned — watching for James...\n");
    console.log("💡 In-game commands (type in Minecraft chat):");
    console.log("   label mining    — tag session as mining footage");
    console.log("   label combat    — tag session as combat footage");
    console.log("   label building  — tag session as building footage");
    console.log("   record stop     — stop recording\n");
    startRecording();
});

observer.on("kicked",  r => console.error("\nKicked:", r));
observer.on("error",   e => console.error("\nError:",  e.message));

process.on("SIGINT", () => {
    console.log(`\n\n✅ ${frameCount} frames saved to:\n   ${logFile}\n`);
    process.exit(0);
});
