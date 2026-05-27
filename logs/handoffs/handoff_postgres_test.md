# Handoff — PostgreSQL Database Tool Verification Test
*Date: 2026-05-27 | Session: Testing Hayeong's database tool end-to-end*

---

## Purpose

This is a functional test of Hayeong's database tool. The goal is NOT to build
anything meaningful — it is to verify that the full cycle works correctly:

  create database → create tables → insert data → query data → analyze data

The test uses a simple made-up dataset: a small music library. It is low stakes,
easy to reason about, and exercises every major action the database tool supports.

If this test passes cleanly, the database tool is confirmed working end-to-end
and Hayeong is ready to use it for real projects.

---

## What Hayeong Should Do

Hayeong executes this herself using her database tool. She should narrate each
step as she goes — what she is doing and what result came back. If anything
returns an [ERROR], she should report it clearly and stop rather than continuing.

James will observe. This is a test of Hayeong's ability to use the tool
correctly, not just whether the tool works in isolation.

---

## The Test Sequence

### Step 1 — Check what databases exist

Use the database tool with:
```
action: list_dbs
```

Expected: A list of existing databases. Should include "hayeong" if it was
auto-created. Report back what is found before continuing.

---

### Step 2 — Create a test database

```
action: create_db
database: music_test
```

Expected: [SUCCESS] database "music_test" created.

---

### Step 3 — Create the artists table

```
action: create_table
database: music_test
table: artists
schema: {
    "artist_id": "SERIAL PRIMARY KEY",
    "name": "VARCHAR(100) NOT NULL",
    "genre": "VARCHAR(50)",
    "country": "VARCHAR(50)",
    "active": "BOOLEAN DEFAULT TRUE"
}
```

Expected: [SUCCESS] table "artists" created.

---

### Step 4 — Create the albums table

```
action: create_table
database: music_test
table: albums
schema: {
    "album_id": "SERIAL PRIMARY KEY",
    "artist_id": "INTEGER REFERENCES artists(artist_id)",
    "title": "VARCHAR(150) NOT NULL",
    "release_year": "INTEGER",
    "genre": "VARCHAR(50)",
    "total_tracks": "INTEGER"
}
```

Expected: [SUCCESS] table "albums" created.
Note: This table has a foreign key linking back to artists — this is what makes
it relational. An album belongs to an artist.

---

### Step 5 — Insert artists (bulk insert)

```
action: insert
database: music_test
table: artists
data: [
    {"name": "Kendrick Lamar", "genre": "Hip-Hop", "country": "USA", "active": true},
    {"name": "Hozier", "genre": "Folk Rock", "country": "Ireland", "active": true},
    {"name": "Hiatus Kaiyote", "genre": "Neo-Soul", "country": "Australia", "active": true},
    {"name": "Cigarettes After Sex", "genre": "Dream Pop", "country": "USA", "active": true},
    {"name": "Nujabes", "genre": "Lo-Fi Hip-Hop", "country": "Japan", "active": false}
]
```

Expected: [SUCCESS] 5 rows inserted into artists.

---

### Step 6 — Insert albums

```
action: insert
database: music_test
table: albums
data: [
    {"artist_id": 1, "title": "good kid, m.A.A.d city", "release_year": 2012, "genre": "Hip-Hop", "total_tracks": 12},
    {"artist_id": 1, "title": "To Pimp a Butterfly", "release_year": 2015, "genre": "Hip-Hop", "total_tracks": 16},
    {"artist_id": 1, "title": "Mr. Morale & The Big Steppers", "release_year": 2022, "genre": "Hip-Hop", "total_tracks": 18},
    {"artist_id": 2, "title": "Hozier", "release_year": 2014, "genre": "Folk Rock", "total_tracks": 13},
    {"artist_id": 2, "title": "Wasteland, Baby!", "release_year": 2019, "genre": "Folk Rock", "total_tracks": 14},
    {"artist_id": 3, "title": "Tawk Tomahawk", "release_year": 2012, "genre": "Neo-Soul", "total_tracks": 8},
    {"artist_id": 3, "title": "Choose Your Weapon", "release_year": 2015, "genre": "Neo-Soul", "total_tracks": 16},
    {"artist_id": 4, "title": "Cigarettes After Sex", "release_year": 2017, "genre": "Dream Pop", "total_tracks": 9},
    {"artist_id": 5, "title": "Modal Soul", "release_year": 2005, "genre": "Lo-Fi Hip-Hop", "total_tracks": 16},
    {"artist_id": 5, "title": "Metaphorical Music", "release_year": 2003, "genre": "Lo-Fi Hip-Hop", "total_tracks": 14}
]
```

Expected: [SUCCESS] 10 rows inserted into albums.

---

### Step 7 — Basic query: list all artists

```
action: query
database: music_test
query: SELECT * FROM artists ORDER BY name
```

Expected: [SUCCESS] — 5 rows returned, all artists listed alphabetically.
Hayeong should describe what came back, not just report success.

---

### Step 8 — Relational query: join artists and albums

```
action: query
database: music_test
query: SELECT artists.name, albums.title, albums.release_year 
       FROM albums 
       JOIN artists ON albums.artist_id = artists.artist_id 
       ORDER BY artists.name, albums.release_year
```

Expected: [SUCCESS] — 10 rows returned showing each album with its artist name.
This is the key test — it proves the foreign key relationship works and Hayeong
can query across tables correctly.

---

### Step 9 — Filtered query: albums after 2014

```
action: query
database: music_test
query: SELECT artists.name, albums.title, albums.release_year
       FROM albums
       JOIN artists ON albums.artist_id = artists.artist_id
       WHERE albums.release_year > 2014
       ORDER BY albums.release_year
```

Expected: [SUCCESS] — Should return 5 albums (To Pimp a Butterfly, Wasteland Baby,
Choose Your Weapon, Cigarettes After Sex, Mr. Morale). Hayeong should name them.

---

### Step 10 — Data reader analysis

Switch to the data_reader tool:

```
action: analyze
database: music_test
table: albums
```

Expected: [SUCCESS] — A natural language summary describing the albums table:
column types, value ranges, any patterns noticed. Hayeong should read this
analysis and summarize what she learned about the dataset in her own words.

---

### Step 11 — Describe the tables

```
action: describe_table
database: music_test
table: artists
```

```
action: describe_table
database: music_test
table: albums
```

Expected: [SUCCESS] — Column names, types, and constraints for each table.
This confirms Hayeong can inspect her own database structure.

---

### Step 12 — List tables in the database

```
action: list_tables
database: music_test
```

Expected: [SUCCESS] — Returns ["artists", "albums"].

---

## What to Report Back to James

After completing all steps, Hayeong should give James a summary that includes:

1. Which steps succeeded and which (if any) had errors
2. What the relational join query returned — name the albums and artists
3. What the data_reader analysis said about the albums table
4. Whether PostgreSQL or SQLite fallback was used (she can tell from the
   tool response — it will indicate which backend ran)
5. Her own honest assessment: did the tool feel natural to use, or were
   there moments where she was uncertain what to do next?

That last point matters — James wants to know if the tool works AND if
Hayeong can use it fluidly as part of her reasoning, not just mechanically.

---

## If PostgreSQL Is Not Running

The tool will automatically fall back to SQLite stored at H:/Databases/sqlite/.
This is expected and acceptable for this test. The SQL syntax is identical.
Hayeong should note which backend was used in her summary.

If both fail, report the exact [ERROR] message — do not attempt workarounds.

---

## After the Test — Cleanup (Optional)

If James wants to clean up after the test:
```
action: drop_table
database: music_test
table: albums
```
```
action: drop_table
database: music_test
table: artists
```

The music_test database itself can remain — empty databases take no meaningful
space and it confirms the tool works for future use.

---

## What NOT to Do

- Do not modify main.py
- Do not modify any Memory/ files
- Do not modify Brain/ files
- This is purely a Hayeong-executes-tool test — no code changes needed
- If a step fails, stop and report rather than skipping ahead

---

## Success Criteria

The test passes if:
- All 12 steps complete with [SUCCESS]
- The JOIN query returns correct data linking albums to artists
- The data_reader analyze action returns a meaningful summary
- Hayeong can describe what she built and what the data shows

The test is informative (not a failure) if:
- SQLite fallback was used instead of PostgreSQL — note it and continue
- Step 10 (analyze) returns less detail than expected — note the gap
