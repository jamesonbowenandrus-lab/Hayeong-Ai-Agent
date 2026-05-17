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

const STATE_FILE   = path.join(__dirname, "state", "minecraft_state.json");
const COMMAND_FILE = path.join(__dirname, "state", "minecraft_command.json");

// -------------------------
// Bot
// -------------------------
const bot = mineflayer.createBot({
    host: MC_HOST, port: MC_PORT,
    username: MC_USERNAME, version: MC_VERSION,
});
bot.loadPlugin(pathfinder);
bot.setMaxListeners(20);

// -------------------------
// Tracked state
// -------------------------
let currentAction = "idle";
let lastEvent     = "starting";

// -------------------------
// Behavior state
// -------------------------
let currentBehavior = {
    mode:     "idle",
    target:   null,
    position: null,
    since:    Date.now(),
};

function setBehavior(mode, params = {}) {
    const prev = currentBehavior.mode;
    currentBehavior = {
        mode,
        target:   params.target   || null,
        position: params.position || null,
        since:    Date.now(),
    };
    console.log(`[behavior] ${prev} → ${mode}${params.target ? ` (${params.target})` : ''}`);
    lastEvent = `behavior: ${mode}`;
}

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
// Food lists
// -------------------------
const KNOWN_FOOD_NAMES = new Set([
    'bread','apple','cooked_beef','cooked_porkchop','cooked_mutton','cooked_chicken',
    'cooked_salmon','cooked_cod','cooked_rabbit','golden_carrot','carrot','potato',
    'baked_potato','beetroot','melon_slice','sweet_berries','dried_kelp','pumpkin_pie',
    'mushroom_stew','rabbit_stew','beef','porkchop','mutton','chicken','salmon','cod',
    'rabbit','rotten_flesh','spider_eye','cookie',
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
            behavior:       currentBehavior,
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

let isEating = false;

function foodScore(itemName) {
    const high = [
        'cooked_beef','cooked_porkchop','cooked_mutton','cooked_chicken',
        'cooked_salmon','cooked_cod','cooked_rabbit','golden_carrot',
        'bread','baked_potato','pumpkin_pie',
    ];
    const mid = [
        'carrot','potato','beetroot','apple','melon_slice','sweet_berries','dried_kelp',
    ];
    if (high.includes(itemName)) return 2;
    if (mid.includes(itemName))  return 1;
    return 0;
}

function autoEquipBestArmor() {
    const matScore = { netherite: 5, diamond: 4, iron: 3, chainmail: 2, gold: 1, leather: 0 };
    const slots = [
        { slot: "head",  keywords: ["helmet"] },
        { slot: "torso", keywords: ["chestplate"] },
        { slot: "legs",  keywords: ["leggings"] },
        { slot: "feet",  keywords: ["boots"] },
    ];
    for (const { slot, keywords } of slots) {
        const best = bot.inventory.items()
            .filter(i => keywords.some(k => i.name.includes(k)))
            .sort((a, b) => {
                const sa = Object.entries(matScore).find(([m]) => a.name.includes(m))?.[1] ?? -1;
                const sb = Object.entries(matScore).find(([m]) => b.name.includes(m))?.[1] ?? -1;
                return sb - sa;
            })[0];
        if (best) bot.equip(best, slot).catch(() => {});
    }
}

// -------------------------
// Command executor
// Accepts: { command: "...", params: {...}, issued_at: "..." }
// -------------------------
async function executeCommand(cmd) {
    const type = cmd.command;
    const p    = cmd.params || {};
    console.log(`[cmd] ${type}`, Object.keys(p).length ? JSON.stringify(p).slice(0, 80) : "");
    currentAction = type;
    lastEvent     = `command: ${type}`;

    try {
        switch (type) {

            case "follow": {
                const targetName = (p.username || "").toLowerCase();
                const player = targetName
                    ? Object.values(bot.players).find(pl => pl.username.toLowerCase() === targetName)
                    : null;
                const followTarget = (player?.entity ? player : null) || getNearestPlayer();
                if (followTarget?.entity) {
                    bot.pathfinder.setGoal(new goals.GoalFollow(followTarget.entity, 2), true);
                    lastEvent = `following ${followTarget.username}`;
                } else {
                    lastEvent     = "follow failed: no players visible";
                    currentAction = "idle";
                }
                break;
            }

            case "move_to_player": {
                const targetName = (p.username || "").toLowerCase();
                const player = targetName
                    ? Object.values(bot.players).find(pl => pl.username.toLowerCase() === targetName)
                    : null;
                const moveTarget = (player?.entity ? player : null) || getNearestPlayer();
                if (moveTarget?.entity) {
                    const ep = moveTarget.entity.position;
                    bot.pathfinder.setGoal(new goals.GoalNear(ep.x, ep.y, ep.z, 2), true);
                    lastEvent = `moving to ${moveTarget.username}`;
                } else {
                    lastEvent     = "move_to_player failed: no players visible";
                    currentAction = "idle";
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

                // Fallback to any available log type when given a generic log/wood name
                if (!blockId || !bot.findBlock({ matching: blockId, maxDistance: 48 })) {
                    if (blockName.includes('log') || blockName.includes('wood')) {
                        const logTypes = ['oak_log','spruce_log','birch_log','jungle_log',
                                          'acacia_log','dark_oak_log','mangrove_log'];
                        for (const logType of logTypes) {
                            const altId = bot.registry.blocksByName[logType]?.id;
                            if (!altId) continue;
                            if (bot.findBlock({ matching: altId, maxDistance: 48 })) {
                                blockId = altId; resolvedName = logType; break;
                            }
                        }
                    }
                }

                if (!blockId) { currentAction = "idle"; break; }
                const b = bot.findBlock({ matching: blockId, maxDistance: 48 });
                if (!b) { currentAction = "idle"; break; }

                // Equip best tool for this block type
                const toolHint = blockName.includes('log') || blockName.includes('wood') ? 'axe'
                    : blockName.includes('ore') || blockName.includes('stone') || blockName.includes('rock') ? 'pickaxe'
                    : blockName.includes('dirt') || blockName.includes('sand') || blockName.includes('gravel') ? 'shovel'
                    : null;
                if (toolHint) {
                    const tool = bot.inventory.items()
                        .filter(i => i.name.includes(toolHint))
                        .sort((a, b) => weaponScore(b) - weaponScore(a))[0];
                    if (tool) await bot.equip(tool, "hand").catch(() => {});
                }

                lastEvent = `mining ${resolvedName}`;
                // Move close enough to interact, then dig
                await bot.pathfinder.goto(new goals.GoalNear(b.position.x, b.position.y, b.position.z, 3));
                try {
                    const fresh = bot.findBlock({ matching: blockId, maxDistance: 6 });
                    if (fresh) {
                        await bot.dig(fresh);
                        lastEvent     = `mined ${resolvedName}`;
                        currentAction = "idle";
                        writeState();
                    } else {
                        currentAction = "idle";
                    }
                } catch(e) {
                    console.error("Dig error:", e.message);
                    currentAction = "idle";
                }
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

            case "wear_armor": {
                const armorMap = { helmet: "head", chestplate: "torso", leggings: "legs", boots: "feet" };
                const tierScore = i => {
                    const order = ["leather","golden","chainmail","iron","diamond","netherite"];
                    for (let idx = order.length - 1; idx >= 0; idx--) {
                        if (i.name.includes(order[idx])) return idx;
                    }
                    return -1;
                };
                for (const [suffix, slot] of Object.entries(armorMap)) {
                    const best = bot.inventory.items()
                        .filter(i => i.name.includes(suffix))
                        .sort((a, b) => tierScore(b) - tierScore(a))[0];
                    if (best) bot.equip(best, slot).catch(() => {});
                }
                lastEvent     = "equipping best armor";
                currentAction = "idle";
                break;
            }

            case "eat": {
                if (isEating)      { console.log("   Already eating"); break; }
                if (bot.food >= 18){ console.log("   Not hungry, skipping eat"); currentAction = "idle"; break; }
                const searchTerm = p.item ? p.item.replace(/_/g, " ").toLowerCase() : null;
                const foodItem = searchTerm
                    ? bot.inventory.items().find(i => i.name.replace(/_/g, " ").toLowerCase().includes(searchTerm))
                    : bot.inventory.items()
                        .filter(i => bot.registry.itemsByName[i.name]?.food || KNOWN_FOOD_NAMES.has(i.name))
                        .sort((a, b) => foodScore(b.name) - foodScore(a.name))[0];
                if (foodItem) {
                    isEating  = true;
                    lastEvent = `eating ${foodItem.name}`;
                    bot.equip(foodItem, "hand")
                        .then(() => bot.consume())
                        .then(() => new Promise(r => setTimeout(r, 1500)))
                        .catch(e => console.error("Eat error:", e.message))
                        .finally(() => { isEating = false; });
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

            case "set_behavior": {
                const mode   = p.mode   || "idle";
                const target = p.target || null;
                setBehavior(mode, { target });
                break;
            }

            case "pickup_nearby_items": {
                const items = Object.values(bot.entities)
                    .filter(e => e.name === "item" && e.position?.distanceTo(bot.entity.position) < 10)
                    .sort((a, b) =>
                        a.position.distanceTo(bot.entity.position) -
                        b.position.distanceTo(bot.entity.position)
                    );
                if (items.length === 0) {
                    console.log("[pickup] No items nearby");
                    currentAction = "idle";
                } else {
                    const closest = items[0];
                    bot.pathfinder.setGoal(new goals.GoalNear(
                        closest.position.x, closest.position.y, closest.position.z, 1
                    ));
                    lastEvent = `picking up item`;
                }
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
            executeCommand(cmd).catch(e => console.error("[cmd] Unhandled error:", e.message));
        } catch(e) {
            // Silently ignore malformed or already-deleted command files
        }
    }, 500);
}

// -------------------------
// Behavior loop — 500ms, unified movement + combat
// -------------------------
function startBehaviorLoop() {
    setInterval(() => {
        try {
            if (!bot.entity) return;

            const bm = currentBehavior;

            // ── Combat reactivity (always active regardless of mode) ──
            const meleeThreat = Object.values(bot.entities)
                .filter(e => HOSTILE_MOBS.has(e.name) && !RANGED_MOBS.has(e.name) &&
                             e.position?.distanceTo(bot.entity.position) < 5)
                .sort((a, b) => a.position.distanceTo(bot.entity.position) -
                                b.position.distanceTo(bot.entity.position))[0];

            if (meleeThreat) {
                const weapon = bot.inventory.items()
                    .filter(i => i.name.includes("sword") || i.name.includes("axe"))
                    .sort((a, b) => weaponScore(b) - weaponScore(a))[0];
                if (weapon) bot.equip(weapon, "hand").catch(() => {});

                if (meleeThreat.position.distanceTo(bot.entity.position) <= 2.5) {
                    bot.attack(meleeThreat);
                } else {
                    const { x, y, z } = meleeThreat.position;
                    bot.pathfinder.setGoal(new goals.GoalNear(x, y, z, 2), true);
                }
            }

            const rangedThreat = Object.values(bot.entities)
                .filter(e => RANGED_MOBS.has(e.name) &&
                             e.position?.distanceTo(bot.entity.position) < 16)
                .sort((a, b) => a.position.distanceTo(bot.entity.position) -
                                b.position.distanceTo(bot.entity.position))[0];

            if (rangedThreat && !meleeThreat) {
                if (bot.health > 6) {
                    const dist = rangedThreat.position.distanceTo(bot.entity.position);
                    if (dist <= 3) {
                        bot.attack(rangedThreat);
                    } else {
                        const { x, y, z } = rangedThreat.position;
                        bot.pathfinder.setGoal(new goals.GoalNear(x, y, z, 2), true);
                    }
                } else {
                    const pos  = bot.entity.position;
                    const tpos = rangedThreat.position;
                    bot.pathfinder.setGoal(new goals.GoalXZ(
                        pos.x + (pos.x - tpos.x) * 2,
                        pos.z + (pos.z - tpos.z) * 2
                    ));
                    lastEvent = `critical_health_flee: hp ${Math.round(bot.health)}`;
                    writeState();
                }
            }

            // ── Behavior mode execution ──
            switch (bm.mode) {

                case "idle":
                    break;

                case "follow":
                case "escort": {
                    const targetName = bm.target;
                    const targetPlayer = targetName
                        ? Object.values(bot.players).find(p => p.username?.toLowerCase() === targetName.toLowerCase() && p.entity)
                        : getNearestPlayer();

                    if (targetPlayer?.entity) {
                        const dist = targetPlayer.entity.position.distanceTo(bot.entity.position);
                        if (dist > 3) {
                            bot.pathfinder.setGoal(new goals.GoalFollow(targetPlayer.entity, 2), true);
                        }
                        if (bm.mode === "escort") {
                            const nearPlayerMob = Object.values(bot.entities)
                                .filter(e => HOSTILE_MOBS.has(e.name) &&
                                             e.position?.distanceTo(targetPlayer.entity.position) < 6)
                                .sort((a, b) => a.position.distanceTo(targetPlayer.entity.position) -
                                                b.position.distanceTo(targetPlayer.entity.position))[0];
                            if (nearPlayerMob) {
                                const w = bot.inventory.items()
                                    .filter(i => i.name.includes("sword") || i.name.includes("axe"))
                                    .sort((a, b) => weaponScore(b) - weaponScore(a))[0];
                                if (w) bot.equip(w, "hand").catch(() => {});
                                bot.attack(nearPlayerMob);
                            }
                        }
                    }
                    break;
                }

                case "guard": {
                    const threat = Object.values(bot.entities)
                        .filter(e => HOSTILE_MOBS.has(e.name) &&
                                     e.position?.distanceTo(bot.entity.position) < 12)
                        .sort((a, b) => a.position.distanceTo(bot.entity.position) -
                                        b.position.distanceTo(bot.entity.position))[0];
                    if (threat) {
                        const w = bot.inventory.items()
                            .filter(i => i.name.includes("sword") || i.name.includes("axe"))
                            .sort((a, b) => weaponScore(b) - weaponScore(a))[0];
                        if (w) bot.equip(w, "hand").catch(() => {});
                        const dist = threat.position.distanceTo(bot.entity.position);
                        if (dist <= 2.5) {
                            bot.attack(threat);
                        } else {
                            const { x, y, z } = threat.position;
                            bot.pathfinder.setGoal(new goals.GoalNear(x, y, z, 2), true);
                        }
                    } else if (bm.position) {
                        const dist = bot.entity.position.distanceTo(bm.position);
                        if (dist > 3) {
                            bot.pathfinder.setGoal(new goals.GoalNear(
                                bm.position.x, bm.position.y, bm.position.z, 2
                            ));
                        }
                    }
                    break;
                }

                case "explore":
                    // Wander handled by LLM goto commands
                    break;
            }

        } catch(e) {
            console.error("[behavior] Error:", e.message);
        }
    }, 500);
}

// -------------------------
// Hunger loop — 3s with isEating guard
// -------------------------
function startHungerLoop() {
    setInterval(async () => {
        try {
            if (isEating)        return;
            if (bot.food >= 18)  return;
            if (bot.health <= 0) return;

            const foodItems = bot.inventory.items()
                .filter(i => bot.registry.itemsByName[i.name]?.food || KNOWN_FOOD_NAMES.has(i.name))
                .sort((a, b) => foodScore(b.name) - foodScore(a.name));

            if (foodItems.length === 0) return;

            isEating = true;
            await bot.equip(foodItems[0], "hand");
            await bot.consume();
            await new Promise(r => setTimeout(r, 1500));
        } catch(e) {
            // consume() can fail if interrupted — that's fine
        } finally {
            isEating = false;
        }
    }, 3000);
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
                .some(i => bot.registry.itemsByName[i.name]?.food || KNOWN_FOOD_NAMES.has(i.name));
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
                        console.log("[stuck] Hard behavior reset — re-applying current mode");
                        bot.pathfinder.stop();
                        bot.clearControlStates();
                        bot.setControlState("jump", true);
                        setTimeout(() => {
                            try {
                                bot.setControlState("jump", false);
                                const bm = currentBehavior;
                                if (bm.mode === "follow" || bm.mode === "escort") {
                                    const tp = bm.target
                                        ? Object.values(bot.players).find(p => p.username?.toLowerCase() === bm.target?.toLowerCase() && p.entity)
                                        : getNearestPlayer();
                                    if (tp?.entity) {
                                        bot.pathfinder.setGoal(new goals.GoalFollow(tp.entity, 2), true);
                                    }
                                }
                                stuckCounter   = 0;
                                reported.stuck = false;
                            } catch(e) {}
                        }, 600);
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
// Default spawn behavior — auto-follow nearest player after 3s
// -------------------------
function defaultSpawnBehavior() {
    setTimeout(() => {
        try {
            const target = getNearestPlayer();
            if (target?.entity) {
                console.log(`[spawn] Auto-escorting ${target.username}`);
                setBehavior("escort", { target: target.username });
                writeState();
            } else {
                console.log("[spawn] No players visible — staying idle");
            }
        } catch(e) {}
    }, 3000);
    setTimeout(() => autoEquipBestArmor(), 5000);
}

// -------------------------
// Bot events
// -------------------------
bot.on("spawn", () => {
    console.log("✅ Hayeong spawned in Minecraft!");
    require("events").defaultMaxListeners = 20;
    const movements = new Movements(bot);
    movements.canDig         = false;
    movements.canJump        = true;
    movements.allowSprinting = true;
    movements.allowParkour   = true;
    movements.maxDropDown    = 4;
    movements.canOpenDoors   = true;

    // Leaf blocks — mark as cant-break so canDig doesn't apply; pathfinder routes through them
    const leafBlocks = [
        'oak_leaves','spruce_leaves','birch_leaves','jungle_leaves',
        'acacia_leaves','dark_oak_leaves','mangrove_leaves','cherry_leaves',
        'azalea_leaves','flowering_azalea_leaves',
    ];
    for (const name of leafBlocks) {
        const b = bot.registry.blocksByName[name];
        if (b) movements.blocksCantBreak.add(b.id);
    }

    // Doors/gates — protect but allow pathing through (canOpenDoors handles single doors)
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
    startBehaviorLoop();
    startHungerLoop();
    startDiscoveryLoop();
    setInterval(writeState, 2000);
    defaultSpawnBehavior();
});

bot.on("chat", (username, message) => {
    if (username === bot.username) return;
    console.log(`💬 [${username}]: ${message}`);
    // Route in-game player chat to last_event so reasoning loop can respond
    lastEvent = `chat from ${username}: ${message}`;
    writeState();
});

bot.on("playerCollect", (collector, _itemDrop) => {
    if (collector.username !== bot.username) return;
    setTimeout(() => autoEquipBestArmor(), 500);
});

bot.on("entitySpawn", (entity) => {
    if (entity.name !== "item") return;
    if (!bot.entity) return;
    const dist = entity.position?.distanceTo(bot.entity.position);
    if (!dist || dist > 6) return;

    setTimeout(() => {
        try {
            if (!entity.isValid) return;
            const itemDist = entity.position?.distanceTo(bot.entity?.position);
            if (!itemDist || itemDist > 8) return;
            console.log(`[pickup] Item nearby at dist ${itemDist.toFixed(1)}`);
            bot.pathfinder.setGoal(new goals.GoalNear(
                entity.position.x, entity.position.y, entity.position.z, 1
            ));
            lastEvent = `item_nearby`;
            writeState();
        } catch(e) {}
    }, 500);
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
