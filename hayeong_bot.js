// hayeong_bot.js
// Hayeong's Minecraft body.
// node hayeong_bot.js

const mineflayer = require("mineflayer");
const { pathfinder, Movements, goals } = require("mineflayer-pathfinder");
const net = require("net");

const MC_HOST     = "localhost";
const MC_PORT     = 25565;
const MC_USERNAME = "Hayeong";
const MC_VERSION  = "1.21.11";
const BRIDGE_HOST = "127.0.0.1";
const BRIDGE_PORT = 9876;

const bot = mineflayer.createBot({
    host: MC_HOST, port: MC_PORT,
    username: MC_USERNAME, version: MC_VERSION,
});
bot.loadPlugin(pathfinder);

// -------------------------
// Bridge connection
// -------------------------
let bridge = null, bridgeBuffer = "", bridgeReady = false, reconnectTimer = null;

function connectBridge() {
    if (reconnectTimer) clearTimeout(reconnectTimer);
    bridge = new net.Socket();
    bridge.connect(BRIDGE_PORT, BRIDGE_HOST, () => {
        console.log("🐍 Connected to Python AI bridge");
        bridgeReady = true;
        sendEvent("connected");
    });
    bridge.on("data", (data) => {
        bridgeBuffer += data.toString();
        while (bridgeBuffer.includes("\n")) {
            const idx = bridgeBuffer.indexOf("\n");
            const line = bridgeBuffer.slice(0, idx).trim();
            bridgeBuffer = bridgeBuffer.slice(idx + 1);
            if (line) {
                try { executeAction(JSON.parse(line)); }
                catch(e) { console.error("⚠️ Bad JSON from bridge:", line.slice(0,80)); }
            }
        }
    });
    bridge.on("close", () => {
        bridgeReady = false;
        console.log("🔴 Bridge disconnected, retry in 5s");
        reconnectTimer = setTimeout(connectBridge, 5000);
    });
    bridge.on("error", (e) => console.error("Bridge error:", e.message));
}

function sendEvent(type, extra = {}) {
    if (!bridgeReady || !bridge) return;
    try { bridge.write(JSON.stringify({ type, state: getState(), ...extra }) + "\n"); }
    catch(e) {}
}

// -------------------------
// Game state
// -------------------------
function getInventoryLayout() {
    // Returns per-slot layout with zone labels so the Python bridge
    // can run inventory philosophy observations.
    // Slots 0-8 = hotbar, 9-35 = main inventory, 36-39 = armor
    const layout = [];
    try {
        const slots = bot.inventory.slots;
        for (let i = 0; i < slots.length; i++) {
            const item = slots[i];
            if (!item) continue;
            let zone = "other";
            if (i >= 0  && i <= 8)  zone = "hotbar";
            else if (i >= 9  && i <= 35) zone = "main";
            else if (i >= 36 && i <= 39) zone = "armor";
            layout.push({ slot: i, item: item.name, count: item.count, zone });
        }
    } catch(e) {}
    return layout;
}

function getState() {
    const s = {};
    try {
        s.health = Math.round(bot.health);
        s.food   = Math.round(bot.food);
        s.position = bot.entity ? {
            x: Math.round(bot.entity.position.x),
            y: Math.round(bot.entity.position.y),
            z: Math.round(bot.entity.position.z),
        } : null;
        s.time_of_day = bot.time?.timeOfDay ?? null;
        s.is_raining  = bot.isRaining ?? false;
        s.nearby_players = Object.values(bot.players)
            .filter(p => p.entity && p.username !== bot.username)
            .map(p => p.username);
        s.inventory = bot.inventory.items().slice(0,15).map(i => `${i.count}x ${i.name}`);
        s.inventory_layout = getInventoryLayout();
        s.nearby_mobs = Object.values(bot.entities)
            .filter(e => e.type === "mob" && e.position?.distanceTo(bot.entity.position) < 20)
            .slice(0, 8)
            .map(e => ({
                name: e.name,
                dist: Math.round(e.position.distanceTo(bot.entity.position)),
                type: RANGED_MOBS.has(e.name) ? "ranged" : "melee"
            }));
    } catch(e) {}
    return s;
}

// -------------------------
// Hostile mob lists
// -------------------------
const HOSTILE_MOBS = new Set([
    'zombie','skeleton','creeper','spider','cave_spider','enderman',
    'witch','pillager','vindicator','phantom','drowned','husk',
    'stray','blaze','ghast','slime','magma_cube','hoglin','piglin_brute',
    'bogged'
]);
const RANGED_MOBS = new Set([
    'skeleton','stray','bogged','phantom','ghast','pillager','witch','blaze'
]);

// -------------------------
// Execute actions from Python
// -------------------------
function executeAction(action) {
    const { action: type, ...p } = action;
    console.log(`▶ ${type}`, Object.keys(p).length ? JSON.stringify(p).slice(0,60) : "{}");

    try {
        switch(type) {

            case "chat":
                if (p.message) bot.chat(String(p.message).slice(0, 250));
                break;

            case "follow": {
                const target = getNearestPlayer();
                if (target?.entity) {
                    bot.pathfinder.setGoal(new goals.GoalFollow(target.entity, 2), true);
                }
                break;
            }

            case "move_to_player": {
                const target = getNearestPlayer();
                if (target?.entity) {
                    const { x, y, z } = target.entity.position;
                    bot.pathfinder.setGoal(new goals.GoalNear(x, y, z, 2));
                }
                break;
            }

            case "move_to": {
                if (p.x !== undefined) {
                    bot.pathfinder.setGoal(new goals.GoalNear(p.x, p.y, p.z, 1));
                } else if (p.block) {
                    const b = bot.findBlock({
                        matching: bot.registry.blocksByName[p.block]?.id,
                        maxDistance: 32
                    });
                    if (b) bot.pathfinder.setGoal(new goals.GoalBlock(b.position.x, b.position.y, b.position.z));
                    else bot.chat(`Can't find ${p.block} nearby.`);
                }
                break;
            }

            case "stop":
                bot.pathfinder.stop();
                bot.clearControlStates();
                break;

            case "mine": {
                // Simple reliable mine: find block, walk close, dig
                const blockName = p.block || "oak_log";
                const blockId   = bot.registry.blocksByName[blockName]?.id;
                if (!blockId) { bot.chat(`I don't know what ${blockName} is.`); break; }

                const b = bot.findBlock({ matching: blockId, maxDistance: 48 });
                if (!b) { bot.chat(`No ${blockName} nearby.`); break; }

                console.log(`   Mining ${blockName} at ${b.position}`);

                // Walk to within reach, then dig
                const mineGoal = new goals.GoalNear(b.position.x, b.position.y, b.position.z, 3);
                bot.pathfinder.setGoal(mineGoal);

                let attempts = 0;
                const digInterval = setInterval(async () => {
                    attempts++;
                    if (attempts > 20) { clearInterval(digInterval); return; }

                    const dist = bot.entity.position.distanceTo(b.position);
                    if (dist <= 4) {
                        clearInterval(digInterval);
                        bot.pathfinder.stop();
                        try {
                            // Re-find the block in case it moved or changed
                            const fresh = bot.findBlock({ matching: blockId, maxDistance: 6 });
                            if (fresh) {
                                await bot.dig(fresh);
                                console.log(`   ✅ Mined ${blockName}`);
                            }
                        } catch(e) {
                            console.error("   Dig error:", e.message);
                        }
                    }
                }, 500);
                break;
            }

            case "attack": {
                // Attack nearest hostile — prefer melee range
                const mob = getNearestHostile(8);
                if (mob) {
                    const { x, y, z } = mob.position;
                    bot.pathfinder.setGoal(new goals.GoalNear(x, y, z, 2), true);
                    setTimeout(() => { try { bot.attack(mob); } catch(e) {} }, 800);
                }
                break;
            }

            case "flee": {
                // Run away from nearest threat
                const threat = getNearestHostile(20);
                if (threat && bot.entity) {
                    const pos = bot.entity.position;
                    const tpos = threat.position;
                    // Run in opposite direction
                    const fleeX = pos.x + (pos.x - tpos.x) * 2;
                    const fleeZ = pos.z + (pos.z - tpos.z) * 2;
                    bot.pathfinder.setGoal(new goals.GoalXZ(fleeX, fleeZ));
                }
                break;
            }

            case "equip": {
                // Search inventory for item by partial name
                const searchTerm = (p.item || "").replace(/_/g, " ").toLowerCase();
                const item = bot.inventory.items().find(i =>
                    i.name.replace(/_/g, " ").toLowerCase().includes(searchTerm)
                );
                if (item) {
                    bot.equip(item, "hand").catch(e => console.error("Equip error:", e.message));
                } else {
                    console.log(`   No item matching "${p.item}" in inventory`);
                    bot.chat(`I don't have a ${p.item || "that"}.`);
                }
                break;
            }

            case "eat": {
                // Only eat if hungry (food < 18)
                if (bot.food >= 18) { console.log("   Not hungry, skipping eat"); break; }
                const searchTerm = p.item ? p.item.replace(/_/g, " ").toLowerCase() : null;
                const foodItem = searchTerm
                    ? bot.inventory.items().find(i => i.name.replace(/_/g, " ").toLowerCase().includes(searchTerm))
                    : bot.inventory.items().find(i => bot.registry.itemsByName[i.name]?.food);
                if (foodItem) {
                    bot.equip(foodItem, "hand")
                        .then(() => bot.consume())
                        .catch(e => console.error("Eat error:", e.message));
                } else {
                    bot.chat("I don't have any food.");
                }
                break;
            }

            case "sleep": {
                const bedNames = ["red_bed","blue_bed","white_bed","green_bed","yellow_bed",
                    "purple_bed","cyan_bed","black_bed","orange_bed","pink_bed","gray_bed"];
                let bed = null;
                for (const name of bedNames) {
                    bed = bot.findBlock({ matching: bot.registry.blocksByName[name]?.id, maxDistance: 16 });
                    if (bed) break;
                }
                if (bed) bot.sleep(bed.position).catch(() => bot.chat("Can't sleep right now."));
                else bot.chat("No bed nearby.");
                break;
            }

            case "look_at_player": {
                const target = getNearestPlayer();
                if (target?.entity) {
                    bot.lookAt(target.entity.position.offset(0, 1.6, 0));
                }
                break;
            }

            case "idle":
                // Intentional do-nothing
                break;

            default:
                console.log("⚠️ Unknown action:", type);
        }
    } catch(e) {
        console.error(`Error in ${type}:`, e.message);
    }
}

// -------------------------
// Helper: nearest player
// -------------------------
function getNearestPlayer() {
    return Object.values(bot.players)
        .filter(p => p.entity && p.username !== bot.username)
        .sort((a,b) =>
            a.entity.position.distanceTo(bot.entity.position) -
            b.entity.position.distanceTo(bot.entity.position)
        )[0] || null;
}

// -------------------------
// Helper: nearest hostile mob
// -------------------------
function getNearestHostile(maxDist = 8) {
    return Object.values(bot.entities)
        .filter(e => HOSTILE_MOBS.has(e.name) &&
                     e.position?.distanceTo(bot.entity.position) < maxDist)
        .sort((a,b) =>
            a.position.distanceTo(bot.entity.position) -
            b.position.distanceTo(bot.entity.position)
        )[0] || null;
}

// -------------------------
// Reactive combat loop — 500ms, bypasses AI entirely
// Smart: melee close threats, flee ranged threats when health is low
// -------------------------
function startCombatLoop() {
    setInterval(() => {
        try {
            if (!bot.entity) return;

            const closeMelee = Object.values(bot.entities)
                .filter(e => HOSTILE_MOBS.has(e.name) &&
                             !RANGED_MOBS.has(e.name) &&
                             e.position?.distanceTo(bot.entity.position) < 5)
                .sort((a,b) =>
                    a.position.distanceTo(bot.entity.position) -
                    b.position.distanceTo(bot.entity.position)
                )[0];

            const closeRanged = Object.values(bot.entities)
                .filter(e => RANGED_MOBS.has(e.name) &&
                             e.position?.distanceTo(bot.entity.position) < 16)
                .sort((a,b) =>
                    a.position.distanceTo(bot.entity.position) -
                    b.position.distanceTo(bot.entity.position)
                )[0];

            if (closeMelee) {
                // Equip best weapon
                const weapon = bot.inventory.items()
                    .filter(i => i.name.includes("sword") || i.name.includes("axe"))
                    .sort((a,b) => weaponScore(b) - weaponScore(a))[0];
                if (weapon) bot.equip(weapon, "hand").catch(() => {});

                const dist = closeMelee.position.distanceTo(bot.entity.position);
                if (dist <= 2.5) {
                    bot.attack(closeMelee);
                } else {
                    const { x, y, z } = closeMelee.position;
                    bot.pathfinder.setGoal(new goals.GoalNear(x, y, z, 2), true);
                }
            } else if (closeRanged) {
                // Ranged mob: fight if healthy, flee if not
                if (bot.health > 10) {
                    const dist = closeRanged.position.distanceTo(bot.entity.position);
                    if (dist <= 2.5) {
                        bot.attack(closeRanged);
                    } else {
                        const { x, y, z } = closeRanged.position;
                        bot.pathfinder.setGoal(new goals.GoalNear(x, y, z, 2), true);
                    }
                } else {
                    // Flee — run opposite direction
                    const pos  = bot.entity.position;
                    const tpos = closeRanged.position;
                    const fleeX = pos.x + (pos.x - tpos.x) * 3;
                    const fleeZ = pos.z + (pos.z - tpos.z) * 3;
                    bot.pathfinder.setGoal(new goals.GoalXZ(Math.round(fleeX), Math.round(fleeZ)));
                }
            }
        } catch(e) {}
    }, 500);
}

function weaponScore(item) {
    const tiers = { wooden: 1, stone: 2, iron: 3, golden: 2, diamond: 4, netherite: 5 };
    for (const [tier, score] of Object.entries(tiers)) {
        if (item.name.includes(tier)) return score;
    }
    return 0;
}

// -------------------------
// Auto-eat loop — keeps hunger topped up
// -------------------------
function startHungerLoop() {
    setInterval(() => {
        try {
            if (bot.food > 16) return; // only eat if below 16/20
            const food = bot.inventory.items()
                .find(i => bot.registry.itemsByName[i.name]?.food);
            if (food) {
                bot.equip(food, "hand")
                    .then(() => bot.consume())
                    .catch(() => {});
            }
        } catch(e) {}
    }, 10000); // check every 10 seconds
}

// -------------------------
// Safety heartbeat loop
// -------------------------
let safetyInterval = null;
// Track what we've already reported so we don't spam
const reported = { noFood: false, noWeapon: false, stuck: false };
let lastPosition = null;
let stuckCounter = 0;

function startSafetyLoop() {
    if (safetyInterval) return;
    safetyInterval = setInterval(() => {
        try {
            const state = getState();

            // Report genuine needs — only once until resolved

            // No food at all and hungry
            const hasFood = bot.inventory.items().some(i => bot.registry.itemsByName[i.name]?.food);
            if (!hasFood && bot.food < 12 && !reported.noFood) {
                reported.noFood = true;
                sendEvent("needs_report", { description: "I'm getting hungry and I'm out of food — can you give me something to eat?" });
            } else if (hasFood) {
                reported.noFood = false; // reset when resolved
            }

            // No weapon and mobs are around
            const hasWeapon = bot.inventory.items().some(i => i.name.includes("sword") || i.name.includes("axe"));
            if (!hasWeapon && state.nearby_mobs?.length > 0 && !reported.noWeapon) {
                reported.noWeapon = true;
                sendEvent("needs_report", { description: "I don't have a weapon and there are mobs nearby — can you give me something to fight with?" });
            } else if (hasWeapon) {
                reported.noWeapon = false;
            }

            // Stuck detection — haven't moved in 30 seconds while a follow/move goal is active
            const pos = bot.entity?.position;
            if (pos && lastPosition) {
                const moved = pos.distanceTo(lastPosition);
                if (moved < 0.5) {
                    stuckCounter++;
                    if (stuckCounter >= 6 && !reported.stuck) { // 30 seconds
                        reported.stuck = true;
                        sendEvent("needs_report", { description: "I think I'm stuck and can't move — can you help?" });
                    }
                } else {
                    stuckCounter = 0;
                    reported.stuck = false;
                }
            }
            lastPosition = pos ? pos.clone() : null;

            // Send heartbeat (bridge mostly ignores these now)
            sendEvent("heartbeat");
        } catch(e) {}
    }, 5000);
}



// -------------------------
// Discovery system
// Scans nearby blocks for structures/features James cares about
// Add to WATCH_FOR to make her report new things
// -------------------------
const WATCH_FOR = [
    { name: "village",      blocks: ["village_center", "bell"] },
    { name: "dungeon",      blocks: ["spawner", "mossy_cobblestone"] },
    { name: "mine shaft",   blocks: ["oak_fence", "chain"] },
    { name: "stronghold",   blocks: ["end_portal_frame", "iron_bars"] },
    { name: "desert temple",blocks: ["chiseled_sandstone", "orange_terracotta"] },
    { name: "jungle temple",blocks: ["chiseled_stone_bricks", "dispenser"] },
    { name: "nether portal",blocks: ["obsidian", "crying_obsidian"] },
    { name: "diamonds",     blocks: ["diamond_ore", "deepslate_diamond_ore"] },
    { name: "ancient debris",blocks: ["ancient_debris"] },
];
const alreadyReported = new Set();

function startDiscoveryLoop() {
    setInterval(() => {
        try {
            if (!bot.entity) return;
            const pos = bot.entity.position;

            for (const item of WATCH_FOR) {
                for (const blockName of item.blocks) {
                    const blockType = bot.registry.blocksByName[blockName];
                    if (!blockType) continue;
                    const found = bot.findBlock({ matching: blockType.id, maxDistance: 20 });
                    if (found) {
                        // Use a grid-based key so we don't report the same structure twice
                        const key = item.name + ":" + Math.round(found.position.x/16) + "," + Math.round(found.position.z/16);
                        if (!alreadyReported.has(key)) {
                            alreadyReported.add(key);
                            const p = found.position;
                            sendEvent("discovery", {
                                description: `${item.name} at (${p.x}, ${p.y}, ${p.z})`
                            });
                            console.log(`🔍 Discovery: ${item.name} at ${p.x},${p.y},${p.z}`);
                        }
                        break;
                    }
                }
            }
        } catch(e) {}
    }, 15000); // scan every 15 seconds
}

// -------------------------
// Bot events
// -------------------------
bot.on("spawn", () => {
    console.log("✅ Hayeong spawned in Minecraft!");
    const mcData    = require("minecraft-data")(bot.version);
    const movements = new Movements(bot);
    movements.canDig = false; // don't dig through walls/doors while pathfinding

    // Protect doors and gates from pathfinder
    const dontBreak = [
        'oak_door','spruce_door','birch_door','jungle_door','acacia_door',
        'dark_oak_door','mangrove_door','cherry_door','bamboo_door','iron_door',
        'oak_fence_gate','spruce_fence_gate','birch_fence_gate','acacia_fence_gate',
        'oak_trapdoor','spruce_trapdoor','iron_trapdoor'
    ];
    for (const name of dontBreak) {
        const b = bot.registry.blocksByName[name];
        if (b) movements.blocksCantBreak.add(b.id);
    }
    bot.pathfinder.setMovements(movements);

    connectBridge();
    startSafetyLoop();
    startCombatLoop();
    startHungerLoop();
    setTimeout(() => sendEvent("spawn"), 1500);
});

bot.on("chat", (username, message) => {
    if (username === bot.username) return;
    console.log(`💬 [${username}]: ${message}`);
    sendEvent("chat", { sender: username, message });
});

bot.on("health", () => {
    if (bot.health < 8) sendEvent("low_health", { health: bot.health });
});

bot.on("death",        ()       => { console.log("💀 Hayeong died"); sendEvent("death"); });
bot.on("playerJoined", (player) => { if (player.username !== bot.username) sendEvent("player_joined", { player: player.username }); });
bot.on("playerLeft",   (player) => { sendEvent("player_left", { player: player.username }); });
bot.on("kicked",       reason   => console.error("Kicked:", reason));
bot.on("error",        err      => console.error("Bot error:", err.message));

console.log(`🚀 Connecting to ${MC_HOST}:${MC_PORT} as ${MC_USERNAME}...`);