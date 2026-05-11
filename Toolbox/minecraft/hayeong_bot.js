// hayeong_bot.js
// Hayeong's Minecraft body.
// node hayeong_bot.js [host] [port] [username] [version]

const mineflayer = require("mineflayer");
const { pathfinder, Movements, goals } = require("mineflayer-pathfinder");
const fs   = require("fs");
const path = require("path");

// -------------------------
// Config
// -------------------------
const MC_HOST      = process.argv[2] || "127.0.0.1";
const MC_PORT      = parseInt(process.argv[3]) || 25565;
const MC_USERNAME  = process.argv[4] || "Hayeong";
const MC_VERSION   = process.argv[5] || false;

const STATE_FILE   = path.join(__dirname, "..", "..", "Brain", "state", "minecraft_state.json");
const COMMAND_FILE = path.join(__dirname, "..", "..", "Brain", "state", "minecraft_command.json");

// -------------------------
// Bot
// -------------------------
const bot = mineflayer.createBot({
    host: MC_HOST, port: MC_PORT,
    username: MC_USERNAME, version: MC_VERSION,
});
bot.loadPlugin(pathfinder);

// -------------------------
// Tracked state
// -------------------------
let currentAction = "idle";
let lastEvent     = "starting";

// -------------------------
// Mob lists
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
// State file writer
// -------------------------
function writeState(extra = {}) {
    try {
        const state = {
            connected:      true,
            username:       bot.username,
            position:       bot.entity ? {
                x: Math.round(bot.entity.position.x * 10) / 10,
                y: Math.round(bot.entity.position.y * 10) / 10,
                z: Math.round(bot.entity.position.z * 10) / 10,
            } : null,
            health:         Math.round(bot.health ?? 0),
            food:           Math.round(bot.food   ?? 0),
            dimension:      bot.game?.dimension ?? "unknown",
            nearby_players: Object.values(bot.players || {})
                .filter(p => p.username !== bot.username && p.entity)
                .map(p => p.username),
            nearby_mobs:    Object.values(bot.entities || {})
                .filter(e => HOSTILE_MOBS.has(e.name) &&
                             e.position?.distanceTo(bot.entity?.position) < 20)
                .slice(0, 8)
                .map(e => ({ name: e.name, dist: Math.round(e.position.distanceTo(bot.entity.position)) })),
            current_action: currentAction,
            last_event:     lastEvent,
            updated_at:     new Date().toISOString(),
            ...extra,
        };
        fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
    } catch(e) {
        console.error("[state] Write failed:", e.message);
    }
}

function writeDisconnected(reason = "disconnected") {
    try {
        fs.writeFileSync(STATE_FILE, JSON.stringify({
            connected:  false,
            last_event: reason,
            updated_at: new Date().toISOString(),
        }, null, 2));
    } catch(e) {}
}

// -------------------------
// Helpers
// -------------------------
function getNearestPlayer() {
    if (!bot.entity) return null;
    return Object.values(bot.players)
        .filter(p => p.entity && p.username !== bot.username)
        .sort((a, b) =>
            a.entity.position.distanceTo(bot.entity.position) -
            b.entity.position.distanceTo(bot.entity.position)
        )[0] || null;
}

function getNearestHostile(maxDist = 8) {
    if (!bot.entity) return null;
    return Object.values(bot.entities)
        .filter(e => HOSTILE_MOBS.has(e.name) &&
                     e.position?.distanceTo(bot.entity.position) < maxDist)
        .sort((a, b) =>
            a.position.distanceTo(bot.entity.position) -
            b.position.distanceTo(bot.entity.position)
        )[0] || null;
}

function weaponScore(item) {
    const tiers = { wooden: 1, stone: 2, iron: 3, golden: 2, diamond: 4, netherite: 5 };
    for (const [tier, score] of Object.entries(tiers)) {
        if (item.name.includes(tier)) return score;
    }
    return 0;
}

// -------------------------
// Command executor
// Accepts: { command: "...", params: {...}, issued_at: "..." }
// -------------------------
function executeCommand(cmd) {
    const type = cmd.command;
    const p    = cmd.params || {};
    console.log(`[cmd] ${type}`, Object.keys(p).length ? JSON.stringify(p).slice(0, 80) : "");
    currentAction = type;
    lastEvent     = `command: ${type}`;

    try {
        switch (type) {

            case "follow": {
                const targetName = p.username;
                if (targetName) {
                    const player = bot.players[targetName];
                    if (player?.entity) {
                        bot.pathfinder.setGoal(new goals.GoalFollow(player.entity, 2), true);
                        lastEvent = `following ${targetName}`;
                    } else {
                        lastEvent     = `follow failed: ${targetName} not visible`;
                        currentAction = "idle";
                    }
                } else {
                    const nearest = getNearestPlayer();
                    if (nearest?.entity) {
                        bot.pathfinder.setGoal(new goals.GoalFollow(nearest.entity, 2), true);
                        lastEvent = `following ${nearest.username}`;
                    } else {
                        lastEvent     = "follow failed: no players visible";
                        currentAction = "idle";
                    }
                }
                break;
            }

            case "stop": {
                bot.pathfinder.setGoal(null);
                bot.clearControlStates();
                currentAction = "idle";
                lastEvent     = "stopped";
                break;
            }

            case "goto": {
                const { x, y, z } = p;
                if (x != null && z != null) {
                    bot.pathfinder.setGoal(new goals.GoalNear(
                        x, y ?? bot.entity.position.y, z, 1
                    ));
                    lastEvent = `moving to ${x},${y},${z}`;
                } else {
                    currentAction = "idle";
                }
                break;
            }

            case "jump": {
                bot.setControlState('jump', true);
                setTimeout(() => bot.setControlState('jump', false), 500);
                lastEvent     = "jumped";
                currentAction = "idle";
                break;
            }

            case "chat": {
                const message = p.message;
                if (message) bot.chat(String(message).slice(0, 250));
                currentAction = "idle";
                break;
            }

            case "move_to": {
                if (p.x !== undefined) {
                    bot.pathfinder.setGoal(new goals.GoalNear(p.x, p.y, p.z, 1));
                    lastEvent = `moving to ${p.x},${p.y},${p.z}`;
                } else if (p.block) {
                    const b = bot.findBlock({
                        matching: bot.registry.blocksByName[p.block]?.id,
                        maxDistance: 32,
                    });
                    if (b) {
                        bot.pathfinder.setGoal(new goals.GoalBlock(b.position.x, b.position.y, b.position.z));
                        lastEvent = `moving to ${p.block}`;
                    } else {
                        bot.chat(`Can't find ${p.block} nearby.`);
                        currentAction = "idle";
                    }
                }
                break;
            }

            case "mine": {
                const blockName  = p.block || "oak_log";
                let blockId      = bot.registry.blocksByName[blockName]?.id;
                let resolvedName = blockName;

                // If block unknown or none nearby, try log type alternatives
                if (!blockId || !bot.findBlock({ matching: blockId, maxDistance: 48 })) {
                    if (blockName.includes('log') || blockName.includes('wood')) {
                        const logTypes = ['oak_log','spruce_log','birch_log','jungle_log',
                                          'acacia_log','dark_oak_log','mangrove_log'];
                        for (const logType of logTypes) {
                            const altId = bot.registry.blocksByName[logType]?.id;
                            if (!altId) continue;
                            const altBlock = bot.findBlock({ matching: altId, maxDistance: 48 });
                            if (altBlock) { blockId = altId; resolvedName = logType; break; }
                        }
                    }
                }

                if (!blockId) { currentAction = "idle"; break; }
                const b = bot.findBlock({ matching: blockId, maxDistance: 48 });
                if (!b) { currentAction = "idle"; break; }

                lastEvent = `mining ${resolvedName}`;
                bot.pathfinder.setGoal(new goals.GoalNear(b.position.x, b.position.y, b.position.z, 3));
                let attempts = 0;
                const digInterval = setInterval(async () => {
                    attempts++;
                    if (attempts > 20) { clearInterval(digInterval); currentAction = "idle"; return; }
                    if (bot.entity.position.distanceTo(b.position) <= 4) {
                        clearInterval(digInterval);
                        bot.pathfinder.stop();
                        try {
                            const fresh = bot.findBlock({ matching: blockId, maxDistance: 6 });
                            if (fresh) {
                                await bot.dig(fresh);
                                lastEvent     = `mined ${blockName}`;
                                currentAction = "idle";
                                writeState();
                            }
                        } catch(e) {
                            console.error("Dig error:", e.message);
                            currentAction = "idle";
                        }
                    }
                }, 500);
                break;
            }

            case "attack": {
                const mob = getNearestHostile(8);
                if (mob) {
                    const { x, y, z } = mob.position;
                    bot.pathfinder.setGoal(new goals.GoalNear(x, y, z, 2), true);
                    setTimeout(() => { try { bot.attack(mob); } catch(e) {} }, 800);
                    lastEvent = `attacking ${mob.name}`;
                } else {
                    currentAction = "idle";
                }
                break;
            }

            case "flee": {
                const threat = getNearestHostile(20);
                if (threat && bot.entity) {
                    const pos  = bot.entity.position;
                    const tpos = threat.position;
                    bot.pathfinder.setGoal(new goals.GoalXZ(
                        pos.x + (pos.x - tpos.x) * 2,
                        pos.z + (pos.z - tpos.z) * 2
                    ));
                    lastEvent = `fleeing from ${threat.name}`;
                } else {
                    currentAction = "idle";
                }
                break;
            }

            case "equip": {
                const searchTerm = (p.item || "").replace(/_/g, " ").toLowerCase();
                const item = bot.inventory.items().find(i =>
                    i.name.replace(/_/g, " ").toLowerCase().includes(searchTerm)
                );
                if (item) {
                    bot.equip(item, "hand").catch(e => console.error("Equip error:", e.message));
                    lastEvent = `equipped ${item.name}`;
                } else {
                    bot.chat(`I don't have a ${p.item || "that"}.`);
                    currentAction = "idle";
                }
                break;
            }

            case "eat": {
                if (bot.food >= 18) { currentAction = "idle"; break; }
                const searchTerm = p.item ? p.item.replace(/_/g, " ").toLowerCase() : null;
                const foodItem = searchTerm
                    ? bot.inventory.items().find(i => i.name.replace(/_/g, " ").toLowerCase().includes(searchTerm))
                    : bot.inventory.items().find(i => bot.registry.itemsByName[i.name]?.food);
                if (foodItem) {
                    bot.equip(foodItem, "hand")
                        .then(() => bot.consume())
                        .catch(e => console.error("Eat error:", e.message));
                    lastEvent = `eating ${foodItem.name}`;
                } else {
                    bot.chat("I don't have any food.");
                    currentAction = "idle";
                }
                break;
            }

            case "sleep": {
                const bedNames = [
                    "red_bed","blue_bed","white_bed","green_bed","yellow_bed",
                    "purple_bed","cyan_bed","black_bed","orange_bed","pink_bed","gray_bed",
                ];
                let bed = null;
                for (const name of bedNames) {
                    bed = bot.findBlock({ matching: bot.registry.blocksByName[name]?.id, maxDistance: 16 });
                    if (bed) break;
                }
                if (bed) {
                    bot.sleep(bed.position).catch(() => bot.chat("Can't sleep right now."));
                    lastEvent = "sleeping";
                } else {
                    bot.chat("No bed nearby.");
                    currentAction = "idle";
                }
                break;
            }

            case "look_at_player": {
                const nearest = getNearestPlayer();
                if (nearest?.entity) {
                    bot.lookAt(nearest.entity.position.offset(0, 1.6, 0));
                    lastEvent = `looking at ${nearest.username}`;
                }
                currentAction = "idle";
                break;
            }

            case "idle":
                currentAction = "idle";
                lastEvent     = "idle";
                break;

            default:
                console.log("[cmd] Unknown command:", type);
                currentAction = "idle";
        }
    } catch(e) {
        console.error(`[cmd] Error in ${type}:`, e.message);
        currentAction = "idle";
    }

    writeState();
}

// -------------------------
// Command file polling — 500ms
// -------------------------
function startCommandPolling() {
    setInterval(() => {
        try {
            if (!fs.existsSync(COMMAND_FILE)) return;
            const raw = fs.readFileSync(COMMAND_FILE, "utf8");
            const cmd = JSON.parse(raw);
            fs.unlinkSync(COMMAND_FILE);
            executeCommand(cmd);
        } catch(e) {
            // Silently ignore malformed or already-deleted command files
        }
    }, 500);
}

// -------------------------
// Combat loop — 500ms, bypasses AI
// -------------------------
function startCombatLoop() {
    setInterval(() => {
        try {
            if (!bot.entity) return;

            const hasWeapon  = bot.inventory.items()
                .some(i => i.name.includes('sword') || i.name.includes('axe'));
            const engageRange = hasWeapon ? 5 : 2.5;

            const closeMelee = Object.values(bot.entities)
                .filter(e => HOSTILE_MOBS.has(e.name) &&
                             !RANGED_MOBS.has(e.name) &&
                             e.position?.distanceTo(bot.entity.position) < engageRange)
                .sort((a, b) =>
                    a.position.distanceTo(bot.entity.position) -
                    b.position.distanceTo(bot.entity.position)
                )[0];

            const closeRanged = Object.values(bot.entities)
                .filter(e => RANGED_MOBS.has(e.name) &&
                             e.position?.distanceTo(bot.entity.position) < 16)
                .sort((a, b) =>
                    a.position.distanceTo(bot.entity.position) -
                    b.position.distanceTo(bot.entity.position)
                )[0];

            // Without weapon and outnumbered — flee instead of fight
            if (!hasWeapon) {
                const threatCount = Object.values(bot.entities)
                    .filter(e => HOSTILE_MOBS.has(e.name) &&
                                 e.position?.distanceTo(bot.entity.position) < 8).length;
                if (threatCount > 1) {
                    const threat = getNearestHostile(8);
                    if (threat) {
                        const pos  = bot.entity.position;
                        const tpos = threat.position;
                        bot.pathfinder.setGoal(new goals.GoalXZ(
                            Math.round(pos.x + (pos.x - tpos.x) * 3),
                            Math.round(pos.z + (pos.z - tpos.z) * 3)
                        ));
                    }
                    return;
                }
            }

            if (closeMelee) {
                const weapon = bot.inventory.items()
                    .filter(i => i.name.includes("sword") || i.name.includes("axe"))
                    .sort((a, b) => weaponScore(b) - weaponScore(a))[0];
                if (weapon) bot.equip(weapon, "hand").catch(() => {});

                if (closeMelee.position.distanceTo(bot.entity.position) <= 2.5) {
                    bot.attack(closeMelee);
                } else {
                    const { x, y, z } = closeMelee.position;
                    bot.pathfinder.setGoal(new goals.GoalNear(x, y, z, 2), true);
                }
            } else if (closeRanged) {
                if (closeRanged.position.distanceTo(bot.entity.position) <= 3) {
                    bot.attack(closeRanged);
                } else if (bot.health > 10) {
                    const { x, y, z } = closeRanged.position;
                    bot.pathfinder.setGoal(new goals.GoalNear(x, y, z, 2), true);
                } else {
                    const pos  = bot.entity.position;
                    const tpos = closeRanged.position;
                    bot.pathfinder.setGoal(new goals.GoalXZ(
                        Math.round(pos.x + (pos.x - tpos.x) * 3),
                        Math.round(pos.z + (pos.z - tpos.z) * 3)
                    ));
                }
            }
        } catch(e) {}
    }, 500);
}

// -------------------------
// Hunger loop — 10s
// -------------------------
function startHungerLoop() {
    setInterval(() => {
        try {
            if (bot.food > 16) return;
            const food = bot.inventory.items()
                .find(i => bot.registry.itemsByName[i.name]?.food);
            if (food) {
                bot.equip(food, "hand")
                    .then(() => bot.consume())
                    .catch(() => {});
            }
        } catch(e) {}
    }, 10000);
}

// -------------------------
// Safety loop — 5s, writes needs to state
// -------------------------
let safetyInterval = null;
const reported     = { noFood: false, noWeapon: false, stuck: false };
let lastPosition   = null;
let stuckCounter   = 0;

function startSafetyLoop() {
    if (safetyInterval) return;
    safetyInterval = setInterval(() => {
        try {
            const hasFood = bot.inventory.items()
                .some(i => bot.registry.itemsByName[i.name]?.food);
            if (!hasFood && bot.food < 12 && !reported.noFood) {
                reported.noFood = true;
                lastEvent = "needs: hungry and out of food";
                writeState();
            } else if (hasFood) {
                reported.noFood = false;
            }

            const hasWeapon = bot.inventory.items()
                .some(i => i.name.includes("sword") || i.name.includes("axe"));
            const nearbyMobCount = Object.values(bot.entities)
                .filter(e => HOSTILE_MOBS.has(e.name) &&
                             e.position?.distanceTo(bot.entity?.position) < 20).length;
            if (!hasWeapon && nearbyMobCount > 0 && !reported.noWeapon) {
                reported.noWeapon = true;
                lastEvent = "needs: no weapon, mobs nearby";
                writeState();
            } else if (hasWeapon) {
                reported.noWeapon = false;
            }

            const pos = bot.entity?.position;
            if (pos && lastPosition) {
                if (pos.distanceTo(lastPosition) < 0.5) {
                    stuckCounter++;
                    if (stuckCounter >= 6 && !reported.stuck) {
                        reported.stuck = true;
                        lastEvent = "needs: stuck, cannot move";
                        writeState();
                    }
                } else {
                    stuckCounter   = 0;
                    reported.stuck = false;
                }
            }
            lastPosition = pos ? pos.clone() : null;

            // Water safety — swim up if submerged
            if (bot.entity) {
                try {
                    const block      = bot.blockAt(bot.entity.position);
                    const blockAbove = bot.blockAt(bot.entity.position.offset(0, 1, 0));
                    const inWater    = block?.name === 'water' || blockAbove?.name === 'water';

                    if (inWater) {
                        bot.setControlState('jump', true);
                        bot.setControlState('forward', false);
                        if (bot.oxygenLevel !== undefined && bot.oxygenLevel < 10) {
                            lastEvent = "low air — surfacing";
                            bot.pathfinder.setGoal(new goals.GoalNear(
                                bot.entity.position.x,
                                bot.entity.position.y + 5,
                                bot.entity.position.z,
                                1
                            ));
                            writeState();
                        }
                    } else {
                        if (currentAction !== 'jump') {
                            bot.setControlState('jump', false);
                        }
                    }
                } catch(e) {}
            }
        } catch(e) {}
    }, 5000);
}

// -------------------------
// Discovery loop — 15s
// -------------------------
const WATCH_FOR = [
    { name: "village",       blocks: ["bell"] },
    { name: "dungeon",       blocks: ["spawner", "mossy_cobblestone"] },
    { name: "mine shaft",    blocks: ["oak_fence", "chain"] },
    { name: "stronghold",    blocks: ["end_portal_frame", "iron_bars"] },
    { name: "desert temple", blocks: ["chiseled_sandstone", "orange_terracotta"] },
    { name: "jungle temple", blocks: ["chiseled_stone_bricks", "dispenser"] },
    { name: "nether portal", blocks: ["crying_obsidian"] },
    { name: "diamonds",      blocks: ["diamond_ore", "deepslate_diamond_ore"] },
    { name: "ancient debris",blocks: ["ancient_debris"] },
];
const alreadyReported = new Set();

function startDiscoveryLoop() {
    setInterval(() => {
        try {
            if (!bot.entity) return;
            for (const item of WATCH_FOR) {
                for (const blockName of item.blocks) {
                    const blockType = bot.registry.blocksByName[blockName];
                    if (!blockType) continue;
                    const found = bot.findBlock({ matching: blockType.id, maxDistance: 20 });
                    if (found) {
                        const key = item.name + ":" +
                            Math.round(found.position.x / 16) + "," +
                            Math.round(found.position.z / 16);
                        if (!alreadyReported.has(key)) {
                            alreadyReported.add(key);
                            const p = found.position;
                            lastEvent = `discovered ${item.name} at (${p.x}, ${p.y}, ${p.z})`;
                            console.log(`🔍 Discovery: ${item.name} at ${p.x},${p.y},${p.z}`);
                            writeState();
                        }
                        break;
                    }
                }
            }
        } catch(e) {}
    }, 15000);
}

// -------------------------
// Bot events
// -------------------------
bot.on("spawn", () => {
    console.log("✅ Hayeong spawned in Minecraft!");
    const movements = new Movements(bot);
    movements.canDig = false;

    const dontBreak = [
        'oak_door','spruce_door','birch_door','jungle_door','acacia_door',
        'dark_oak_door','mangrove_door','cherry_door','bamboo_door','iron_door',
        'oak_fence_gate','spruce_fence_gate','birch_fence_gate','acacia_fence_gate',
        'oak_trapdoor','spruce_trapdoor','iron_trapdoor',
    ];
    for (const name of dontBreak) {
        const b = bot.registry.blocksByName[name];
        if (b) movements.blocksCantBreak.add(b.id);
    }
    bot.pathfinder.setMovements(movements);

    lastEvent     = "spawned";
    currentAction = "idle";
    writeState();

    startCommandPolling();
    startSafetyLoop();
    startCombatLoop();
    startHungerLoop();
    startDiscoveryLoop();
    setInterval(writeState, 2000);
});

bot.on("chat", (username, message) => {
    if (username === bot.username) return;
    console.log(`💬 [${username}]: ${message}`);
    // Chat is logged to terminal only — does not update state file.
    // Dashboard is the only communication channel with Hayeong.
});

bot.on("health", () => {
    if (bot.health < 8) {
        lastEvent = `low health: ${Math.round(bot.health)}/20`;
        writeState();
    }
});

bot.on("death", () => {
    console.log("💀 Hayeong died");
    lastEvent     = "died";
    currentAction = "respawning";
    writeState({ health: 0 });

    setTimeout(() => {
        try {
            if (!bot.entity) return;
            bot.pathfinder.setGoal(null);
            currentAction = "idle";

            const nearbyThreat = getNearestHostile(8);
            if (nearbyThreat) {
                lastEvent     = "fled after respawn";
                currentAction = "flee";
                const pos  = bot.entity.position;
                const tpos = nearbyThreat.position;
                bot.pathfinder.setGoal(new goals.GoalXZ(
                    Math.round(pos.x + (pos.x - tpos.x) * 4),
                    Math.round(pos.z + (pos.z - tpos.z) * 4)
                ));
            } else {
                lastEvent     = "respawned safely";
                currentAction = "idle";
            }
            writeState();
        } catch(e) {}
    }, 1500);
});

bot.on("playerJoined", (player) => {
    if (player.username !== bot.username) {
        lastEvent = `${player.username} joined`;
        writeState();
    }
});

bot.on("playerLeft", (player) => {
    lastEvent = `${player.username} left`;
    writeState();
});

bot.on("diggingCompleted", (block) => {
    lastEvent     = `mined ${block.name}`;
    currentAction = "idle";
    writeState();
});

bot.on("kicked",  reason => { console.error("Kicked:", reason);        writeDisconnected(`kicked: ${reason}`);       });
bot.on("error",   err    => { console.error("Bot error:", err.message); writeDisconnected(`error: ${err.message}`);   });
bot.on("end",     ()     => { console.log("Bot ended.");                writeDisconnected("disconnected");             });

console.log(`🚀 Connecting to ${MC_HOST}:${MC_PORT} as ${MC_USERNAME}...`);
