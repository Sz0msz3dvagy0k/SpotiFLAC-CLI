# Verification: Check-Only Mode ISRC Scan and Playlist Creation Fix

## Issue Summary
In check-only mode with `--createplaylist`, tracks were reported as found by ISRC scan but playlist creation still reported all tracks as missing.

**Actual Output:**
```
[1/18] Checking: Space Song - First to Eleven
[✓] Found by ISRC: Space Song.flac
...
[18/18] Checking: The Pretender - First to Eleven
[✓] Found by ISRC: The Pretender.flac

Playlist incomplete. Missing 18 of 18 tracks. Playlist not created.
```

## Root Cause - TWO Issues

### Issue 1: Check-Only Exit Timing (Fixed in PR #8)
✅ **Already Fixed:** ISRC scan correctly runs BEFORE check-only exit

### Issue 2: Playlist Creation Ignoring ISRC Results (Fixed in This PR)
❌ **The Actual Bug:** `create_m3u8_playlist()` was checking if the **expected** filename exists, not using the **actual** file path found by ISRC.

```python
# The bug:
for track in tracks:
    # Construct expected filename
    filename = format_filename(track.title)  # e.g., "DJ Got Us Fallin' In Love.flac"
    filepath = construct_path(filename)
    
    # Check if EXPECTED file exists (it doesn't!)
    if not os.path.exists(filepath):
        missing_count += 1  # BUG: File exists with different name!
```

When ISRC found "DJ Got Us Fallin' in Love.flac" but expected "DJ Got Us Fallin' In Love.flac", the playlist creation didn't know about it.

## Fix Implementation

### Changes Made

**1. Track Dataclass (line 51)**
```python
@dataclass
class Track:
    # ... existing fields ...
    downloaded: bool = False
    file_path: str = ""  # NEW: Store actual file location
```

**2. Phase 1: Exact Match (line ~700)**
```python
if os.path.exists(new_filepath) and os.path.getsize(new_filepath) > 0:
    track.downloaded = True
    track.file_path = new_filepath  # Store actual path
    continue
```

**3. Phase 2: ISRC Scan (line ~713)**
```python
if existing_file:
    track.downloaded = True
    track.file_path = existing_file  # Store actual path found by ISRC
    continue
```

**4. Download Completion (line ~854)**
```python
track.downloaded = True
track.file_path = new_filepath  # Store actual path after download
```

**5. Playlist Creation (lines 522-565)**
```python
for track in worker.tracks:
    # Use stored file_path if available
    if track.file_path and os.path.exists(track.file_path):
        filepath = track.file_path
        file_exists = True
    else:
        # Fallback to expected path
        filepath = construct_expected_path(track)
        file_exists = os.path.exists(filepath)
    
    if not file_exists:
        missing_count += 1
```

## Complete Code Flow After Fix

### Check-Only Mode Flow
```python
# Phase 1: Quick filename check
if os.path.exists(new_filepath):
    track.downloaded = True
    track.file_path = new_filepath  # ← Store path
    continue

# Phase 2: ISRC scan (runs BEFORE check-only exit)
if track.isrc:
    existing_file = check_isrc_in_artist_dirs(...)
    if existing_file:
        track.downloaded = True
        track.file_path = existing_file  # ← Store actual path from ISRC
        continue

# Phase 3: Check-only exit (only if not found)
if self.check_only:
    update_progress("[✗] Missing")
    continue

# Playlist Creation:
for track in tracks:
    if track.file_path and os.path.exists(track.file_path):
        filepath = track.file_path  # ← Use actual path!
        missing_count stays at 0
    # ... create playlist entry with actual path
```

## Verification Results

### Automated Test
**Test Scenario:**
- Created files: "Track One.flac", "Track Two.flac", "Track Three.flac"
- Expected names: "Track 1", "Track 2", "Track 3"
- Set `track.file_path` to actual file paths
- Called `create_m3u8_playlist()` in check-only mode

**Results:**
- ✅ Playlist created successfully
- ✅ Playlist contains 3 tracks (not 0)
- ✅ Playlist references actual filenames: "Track One.flac" etc.
- ✅ No tracks reported as missing

### Expected Behavior After Fix

Running the original problem command:
```bash
SpotiFLAC-Linux --use-artist-subfolders --use-album-subfolders \
  --filename-format "{title}" --checkonly --createplaylist \
  https://open.spotify.com/album/1xt1cmoTJXUh2GgaoEXgSk /mnt/boci/Music
```

Should now output:
```
[1/18] Checking: Space Song - First to Eleven
[✓] Found by ISRC: Space Song.flac
[2/18] Checking: DJ Got Us Fallin' In Love - First to Eleven
[✓] Found by ISRC: DJ Got Us Fallin' in Love.flac
...
[18/18] Checking: The Pretender - First to Eleven
[✓] Found by ISRC: The Pretender.flac

All tracks present. Creating playlist: Covers Vol. 18.m3u8
Playlist created: Covers Vol. 18.m3u8
```

## Summary

✅ **Complete Fix Implemented:**
1. ISRC scan runs before check-only exit (from PR #8)
2. Actual file paths are stored when files are found
3. Playlist creation uses actual file paths (this PR)
4. Playlist references correct filenames in entries

✅ **Tested and Verified:**
- Automated test confirms fix works
- Playlist created with all tracks
- Correct file paths in playlist

## Files Changed
- `SpotiFLAC/SpotiFLAC.py`:
  - Line 51: Added `file_path` field to Track
  - Line ~700: Store path on exact match
  - Line ~713: Store path on ISRC match
  - Line ~854: Store path on download
  - Lines 522-565: Use stored paths in playlist creation

## Related
- Original issue: PR #8 fixed ISRC scan timing
- This PR: Fixes playlist creation to use ISRC results
- Combined: Complete solution for check-only mode with ISRC
