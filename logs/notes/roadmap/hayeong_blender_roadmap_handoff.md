# HAYEONG — BLENDER ROADMAP STEPS 2-5
## Scope, Self-Improvement, Collaboration, and Selling

*Session Date: April 20, 2026 | Prepared by: Claude (claude.ai)*

This document covers the broader Blender roadmap after Step 1 (pipeline connection) is confirmed working. Read `hayeong_blender_step1_handoff.md` first — do not start this document until the basic pipeline fires cleanly.

This roadmap also includes a significant new addition: **3D printing capability** — Hayeong generating print-ready files and eventually connecting directly to James's 3D printer.

---

## Step 2 — Understanding Hayeong's Current Blender Scope

### 2.1 Goal

After the pipeline is working, run a structured series of test generations to map what Hayeong can reliably do versus where she fails. This is not about making perfect objects — it is about building an honest picture of her current ability before expanding it.

### 2.2 The Test Progression

Run these in order. Do not skip ahead. Each level should succeed reliably before moving to the next.

| Level | Test object | What it validates |
|---|---|---|
| 1 | Plain cube | Pipeline fires, export works |
| 2 | Rectangular box with correct meter dimensions | Unit conversion, dimension accuracy |
| 3 | Simple base cabinet — box with face groups named | Named groups, multi-part objects |
| 4 | Cabinet with toe kick cutout | Boolean operations or manual vertex placement |
| 5 | Cabinet with door panels (separate objects) | Multi-object scenes, relative positioning |
| 6 | Cabinet with shaker-style door inset panel | Detail geometry, face offsets |
| 7 | Farmhouse sink base with apron front | Complex multi-part, open interior |
| 8 | Something with a curve — rounded edge or arch | Curves and bevels in Blender Python |

### 2.3 How Hayeong Reads Her Own Results

After each generation, Hayeong should:

1. Check whether the file was created (`success` field in result dict)
2. Read `blender_log` for any warnings even on success — warnings often predict future failures
3. If failure: read `error` field, identify which Blender API call failed, and attempt to fix before escalating to James
4. Report to James: what was built, what worked, what didn't, what she tried to fix

**The error log is her primary learning input at this stage.** Make sure it surfaces clearly in her response rather than being buried or silently swallowed.

### 2.4 Documenting Her Scope

After completing the test progression, Hayeong should produce a plain language summary of her current scope:

```
Things I can generate reliably:
- [list what passed]

Things I attempted but failed or produced incorrect output:
- [list what failed and why]

Things I haven't tried yet:
- [list what's not been tested]
```

Store this as a memory entry. It becomes her self-awareness baseline that she updates as she improves.

---

## Step 3 — Growing Hayeong's Blender Knowledge

### 3.1 The Self-Improvement Loop

Hayeong improves her Blender capability through a structured iteration loop. This should be implemented as a behavior pattern, not a hard-coded script.

**When Hayeong hits a Blender error she cannot solve from memory:**

1. Read the error message carefully — Blender errors are descriptive
2. Search the web for the specific error or API method that failed:
   - Blender Python API docs: `docs.blender.org/api/current/`
   - Blender Stack Exchange: `blender.stackexchange.com`
   - Blender Artists community: `blenderartists.org`
3. Extract the relevant fix from search results
4. Rewrite the failing portion of the script
5. Retry — up to 3 attempts before flagging to James
6. If successful: store the working approach in memory tagged with what problem it solved
7. If still failing after 3 attempts: report to James with full error context and what was tried

**Memory storage format for learned techniques:**

```
[blender_technique]
problem: bpy.ops.wm.obj_export not found in Blender 3.x
solution: use bpy.ops.export_scene.obj() for Blender versions below 3.3
          use bpy.ops.wm.obj_export() for Blender 3.3 and above
learned: [date]
```

### 3.2 Proactive Learning — Not Just Reactive

Beyond fixing errors, Hayeong should proactively expand her Blender knowledge when there is idle time or when James asks her to learn something specific.

**Proactive learning topics to prioritize (in order):**

1. Blender Python geometry primitives — cubes, cylinders, planes, spheres and how to combine them
2. Boolean modifiers — cutting shapes out of other shapes (essential for doors, cutouts, handles)
3. Bevel modifier — rounding edges so objects don't look cheap and sharp
4. Array modifier — repeating objects (shelves, cabinet rows, fence posts)
5. Material nodes — basic PBR materials, wood textures, metal finishes
6. UV unwrapping via Python — required for textures to apply correctly on export
7. Curve objects — arches, rounded cabinet tops, decorative molding
8. Collections and hierarchy — organizing complex scenes with many parts
9. Camera and lighting setup for renders — good preview images for QC and Etsy listings
10. Export settings per format — what flags matter for STL (3D printing), FBX (game engines), GLTF (web)

### 3.3 Version Awareness

Blender API changes between versions. Hayeong should always be aware of which version is installed and check for version-specific API differences when looking up solutions.

```python
# Add this to the top of every generated script for self-documentation
import bpy
import sys
print(f"Blender version: {bpy.app.version_string}")
print(f"Python version: {sys.version}")
```

---

## Step 4 — Creating Together

### 4.1 The Collaborative Loop

Once Hayeong is reliable enough, the working mode shifts from testing to creating. The loop looks like this:

```
James describes or shows what he wants
        ↓
Hayeong asks clarifying questions if needed (dimensions, style, detail level)
        ↓
Hayeong generates the Blender script and runs it
        ↓
Blender produces the file + optional preview render
        ↓
James reviews (either preview image or imports into Live Home 3D)
        ↓
James gives feedback — "make the doors taller", "add a drawer", "more rounded"
        ↓
Hayeong revises the script and regenerates
        ↓
Repeat until James is happy
```

### 4.2 Revision Handling

Hayeong should maintain the current object spec in working memory across revision cycles. She is not starting from scratch each time — she is modifying a known spec.

**Implementation note:** Store the last generated script and parameter spec in shared state so Hayeong can reference and modify it across multiple turns without James having to re-describe everything.

### 4.3 Projects to Work On Together

- **James's kitchen remodel** — cabinets, sink base, countertop edge profiles, hardware, fixtures
- **Experimental objects** — things neither of them planned, driven by curiosity
- **Hayeong's own ideas** — she should be encouraged to propose objects she wants to try. This develops her taste and judgment alongside her technical skill.

---

## Step 5 — Researching and Creating Sellable Content

### 5.1 The Research-First Approach

Hayeong does not guess what sells — she researches it first. Before generating any product for sale, she investigates the market.

**Research targets:**

| Platform | What to look for |
|---|---|
| Etsy (3D models category) | Best sellers, price ranges, review counts, style trends |
| Sketchfab Store | Popular categories, download counts, pricing |
| Fab (formerly ArtStation Marketplace) | Game-ready asset demand, style guides |
| Itch.io (assets section) | Indie game asset trends, bundle opportunities |
| Printables / Thingiverse | Popular print categories, remix counts |
| MyMiniFactory | Premium print model pricing |

**What Hayeong extracts from research:**
- Which categories have high demand and lower competition
- What price points are standard for different asset types
- What styles are trending (low-poly, realistic, stylized, etc.)
- What file formats buyers expect for each platform
- What makes listings perform well (thumbnail quality, keyword use, bundle value)

### 5.2 Product Categories to Evaluate

Hayeong should research viability of each before committing time to generation:

**3D model packs (Etsy, Sketchfab, Fab):**
- Kitchen and furniture asset packs (direct extension of current work)
- Architectural elements — windows, doors, molding, trim
- Low-poly nature — trees, rocks, terrain pieces
- Game-ready props — crates, barrels, furniture, signage
- Sci-fi and fantasy props — high demand in game dev community

**3D print files (Printables, MyMiniFactory, Etsy):**
- Home organization — hooks, holders, organizers, drawer dividers
- Gaming miniatures and terrain — high demand, strong community
- Custom home decor — vases, planters, wall art, lampshades
- Replacement parts — knobs, handles, brackets, clips
- Cosplay props and accessories
- Fidget and desk toys

**The key insight:** 3D print files are often simpler geometry than game-ready assets but need to meet stricter requirements (manifold mesh, no internal faces, correct wall thickness). Hayeong learns these requirements as part of her 3D printing capability (see Section 6).

### 5.3 The Generation-to-Listing Pipeline

Once a product category is chosen:

1. Hayeong generates the object in Blender
2. Blender renders a clean preview image (multiple angles)
3. Vision Layer reviews the renders for quality
4. Hayeong writes the product listing copy — title, description, tags, keywords
5. James reviews and approves
6. File is packaged (ZIP with all formats buyers expect)
7. Listed on target platform

Hayeong handles steps 1-4 and 6. James handles step 5 approval and the actual platform listing (account management and payment setup are James's domain).

---

## Step 6 — 3D Printing Capability

*This is a new addition to the roadmap based on James having an existing 3D printer he wants to reactivate.*

### 6.1 What This Adds

Blender is one of the most popular tools for designing 3D print files. Adding print capability to Hayeong's Blender pipeline means she can:

- Design objects specifically for physical printing
- Validate that geometry is print-ready (manifold, correct wall thickness, no overhangs beyond printer capability)
- Export STL files (the standard format for 3D printers)
- Eventually connect directly to James's printer and queue prints

### 6.2 3D Print File Requirements — Different From Regular 3D Models

Print files have stricter geometry requirements than visual 3D models. Bake these into a separate print-specific generation prompt:

| Requirement | Why it matters |
|---|---|
| **Manifold mesh** | Every edge shared by exactly 2 faces — no holes, no internal faces. Non-manifold geometry causes print failures. |
| **Wall thickness** | Minimum 1.2mm for FDM printers (standard home printers). Thinner walls collapse during printing. |
| **Overhangs** | Angles greater than 45° from vertical need support structures or redesign. |
| **Flat base** | Object needs a flat face to sit on the print bed. |
| **No floating geometry** | All parts must be connected. Disconnected pieces print separately and may fall. |
| **Units in millimeters** | STL files for printing are typically in millimeters, not meters. |
| **Scale check** | Always confirm the object is the correct real-world size before exporting. |

### 6.3 Blender Print Validation Script

Add a validation step to the blender_gen pipeline for print files:

```python
import bpy
import bmesh

def validate_for_printing(obj):
    """
    Run basic print validation checks on a Blender object.
    Returns list of issues found.
    """
    issues = []

    bm = bmesh.new()
    bm.from_mesh(obj.data)

    # Check for non-manifold edges
    non_manifold = [e for e in bm.edges if not e.is_manifold]
    if non_manifold:
        issues.append(f"Non-manifold edges found: {len(non_manifold)} edges. Object may not print correctly.")

    # Check for interior faces
    interior_faces = [f for f in bm.faces if all(e.is_manifold for e in f.edges) == False]
    if interior_faces:
        issues.append(f"Potential interior faces: {len(interior_faces)}. May cause slicer errors.")

    bm.free()

    if not issues:
        print("HAYEONG_PRINT_VALID: Geometry passed basic print validation.")
    else:
        for issue in issues:
            print(f"HAYEONG_PRINT_ISSUE: {issue}")

    return issues

# Call after building geometry, before export
validate_for_printing(bpy.context.active_object)

# Export as STL for printing (units in millimeters)
bpy.ops.export_mesh.stl(
    filepath="OUTPUT_PATH_PLACEHOLDER",
    use_selection=False,
    global_scale=1000.0,  # convert meters to millimeters
    use_mesh_modifiers=True
)
```

### 6.4 OctoPrint — Direct Printer Connection

Most 3D printers can be connected to OctoPrint, a free open-source print server that runs on a Raspberry Pi or old computer and exposes a full REST API.

**What the OctoPrint API lets Hayeong do:**
- Upload STL or GCODE files to the printer
- Start, pause, and cancel print jobs
- Monitor print progress in real time
- Read temperature data (bed and nozzle)
- Receive notifications when a print finishes or fails
- Take webcam snapshots of the print in progress (if webcam is attached)

**New capability file: `capabilities/octoprint_ctl.py`**

```python
import requests

OCTOPRINT_URL = "http://localhost:5000"  # or local network IP of the Pi
OCTOPRINT_API_KEY = ""  # stored in config, never hardcoded

def upload_and_print(file_path, start_immediately=False):
    """Upload an STL file to OctoPrint and optionally start printing."""
    headers = {"X-Api-Key": OCTOPRINT_API_KEY}

    with open(file_path, "rb") as f:
        response = requests.post(
            f"{OCTOPRINT_URL}/api/files/local",
            headers=headers,
            files={"file": f},
            data={"print": str(start_immediately).lower()}
        )
    return response.json()

def get_print_status():
    """Get current printer status."""
    headers = {"X-Api-Key": OCTOPRINT_API_KEY}
    response = requests.get(f"{OCTOPRINT_URL}/api/job", headers=headers)
    return response.json()

def cancel_print():
    """Cancel the current print job."""
    headers = {"X-Api-Key": OCTOPRINT_API_KEY, "Content-Type": "application/json"}
    response = requests.post(
        f"{OCTOPRINT_URL}/api/job",
        headers=headers,
        json={"command": "cancel"}
    )
    return response.status_code == 204
```

### 6.5 The Full Print Pipeline

```
James asks Hayeong to print something
        ↓
LLM Layer — reasons about object, generates print-specific Blender Python script
        ↓
blender_gen — builds geometry, runs print validation, exports STL
        ↓
Hayeong reads validation report — flags any issues to James before printing
        ↓
James approves (or requests fixes)
        ↓
octoprint_ctl — uploads STL, queues print job
        ↓
Hayeong monitors progress, reports completion or failure
        ↓
Object printed
```

### 6.6 Printer Setup Requirements

Before `octoprint_ctl` can be built and tested:

1. James's 3D printer needs to be running and connected to a computer or Raspberry Pi running OctoPrint
2. OctoPrint API key needs to be generated in OctoPrint settings and stored in Hayeong's config
3. Confirm OctoPrint is accessible on the local network
4. Run a manual test print through the OctoPrint web UI before connecting Hayeong — confirm the printer itself works first

**Do not build `octoprint_ctl` until the printer is physically running and OctoPrint is confirmed working.** Getting the hardware up first is James's task. Once it's running, `octoprint_ctl` is straightforward to build.

---

## Implementation Priority — Full Roadmap

| Step | Task | Depends on | Priority |
|---|---|---|---|
| 1 | `blender_gen` pipeline firing | Blender installed | NOW — see step1 handoff |
| 2 | Test progression — map current scope | blender_gen working | NEXT |
| 2 | Hayeong scope summary stored in memory | Test progression | NEXT |
| 3 | Error log reading + web lookup loop | blender_gen working | NEXT |
| 3 | Memory storage for learned techniques | Error loop | NEXT |
| 4 | Conversational revision loop — spec in working memory | Scope mapped | NEAR-TERM |
| 4 | Kitchen object generation for James's remodel | blender_gen stable | NEAR-TERM |
| 5 | Market research capability for 3D assets | Web access (existing) | NEAR-TERM |
| 5 | Product listing copy generation | model quality confirmed | NEAR-TERM |
| 6 | Print-specific generation prompt + STL export | blender_gen stable | NEAR-TERM |
| 6 | Print validation script in blender_gen pipeline | STL export working | NEAR-TERM |
| 6 | `octoprint_ctl` capability | Printer physically running | WHEN PRINTER READY |
| 6 | Full print pipeline — generate → validate → queue → monitor | octoprint_ctl | WHEN PRINTER READY |

---

## Roadmap Additions

Add to `HAYEONG_ROADMAP.md`:

```
| XX | Blender scope mapping — structured test progression, scope summary stored in memory | blender_gen | ☐ |
| XX | Blender self-improvement loop — error log reading, web lookup, memory storage | blender_gen | ☐ |
| XX | Conversational 3D revision loop — spec in working memory across turns | blender_gen | ☐ |
| XX | 3D market research — Etsy, Sketchfab, Fab, Printables category analysis | web access | ☐ |
| XX | 3D print file generation — print-specific prompt, STL export, manifold validation | blender_gen | ☐ |
| XX | OctoPrint connection — upload STL, queue job, monitor progress | printer running | ☐ |
| XX | Full print pipeline — generate → validate → queue → monitor → complete | octoprint_ctl | ☐ |
| XX | Sellable asset pipeline — research → generate → render → listing copy → package | All above | ☐ |
```

---

*End of Handoff — Steps 2-5 + 3D Printing*
*Prerequisite: `hayeong_blender_step1_handoff.md` must be complete first*
*Generated: April 20, 2026*