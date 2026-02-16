# Summary: Check-Only Mode ISRC Scan Fix - Complete Solution

## Task Overview
Fix the issue where playlist creation reports all tracks as missing even though they were found by ISRC scan in check-only mode.

## Problem Statement (Actual Issue)
When running SpotiFLAC with `--checkonly --createplaylist`:
```
[1/18] Checking: Space Song - First to Eleven
[✓] Found by ISRC: Space Song.flac
...
[18/18] Checking: The Pretender - First to Eleven
[✓] Found by ISRC: The Pretender.flac

Playlist incomplete. Missing 18 of 18 tracks. Playlist not created.
```

All 18 tracks were found by ISRC scan, but playlist creation still reported all as missing.

## Root Cause Analysis

The issue had TWO parts:

### Part 1: Check-Only Exit Timing (Already Fixed in PR #8)
The ISRC scan was correctly positioned BEFORE check-only exit, so files were being found.

### Part 2: Playlist Creation Logic (THE ACTUAL BUG - Fixed in This PR)
The `create_m3u8_playlist()` function was:
1. Reconstructing the **expected** filename from format string
2. Using `os.path.exists(expected_filepath)` to check if file exists
3. **NOT using the actual file path** found by ISRC scan

When ISRC scan found files with slightly different names (e.g., "DJ Got Us Fallin' in Love.flac" vs "DJ Got Us Fallin' In Love.flac"), the playlist creation function didn't know about them.

## Solution Implemented

### Changes Made

1. **Track dataclass** (`SpotiFLAC.py` line 51)
   - Added `file_path: str = ""` field to store actual file location

2. **Phase 1: Exact Filename Match** (line ~700)
   - Set `track.file_path = new_filepath` when file found by exact name

3. **Phase 2: ISRC Scan** (line ~713)
   - Set `track.file_path = existing_file` when file found by ISRC

4. **Download Completion** (line ~854)
   - Set `track.file_path = new_filepath` after successful download

5. **Playlist Creation** (`create_m3u8_playlist` function, lines 522-565)
   - Check if `track.file_path` is set and exists → use it
   - Otherwise → construct expected path and check it
   - Use actual file path in playlist entries

### Code Flow After Fix

```python
# In DownloadWorker.run():
if os.path.exists(new_filepath):
    track.downloaded = True
    track.file_path = new_filepath  # ← Store actual path
    continue

if track.isrc:
    existing_file = check_isrc_in_artist_dirs(...)
    if existing_file:
        track.downloaded = True
        track.file_path = existing_file  # ← Store actual path from ISRC
        continue

# In create_m3u8_playlist():
for track in worker.tracks:
    if track.file_path and os.path.exists(track.file_path):
        filepath = track.file_path  # ← Use stored path!
        file_exists = True
    else:
        filepath = construct_expected_path()
        file_exists = os.path.exists(filepath)
    
    if not file_exists:
        missing_count += 1
```

## Testing & Verification

### Automated Test
Created and ran test that:
- ✅ Creates files with specific names (e.g., "Track One.flac")
- ✅ Sets tracks with different expected names (e.g., "Track 1")
- ✅ Sets `track.file_path` to actual file paths
- ✅ Calls `create_m3u8_playlist()` in check-only mode
- ✅ Verifies playlist is created successfully
- ✅ Verifies playlist references actual file names

Result: **All tests passed!**

### Expected Behavior After Fix

When running the command from the problem statement:
```bash
SpotiFLAC-Linux --use-artist-subfolders --use-album-subfolders \
  --filename-format "{title}" --checkonly --createplaylist \
  https://open.spotify.com/album/1xt1cmoTJXUh2GgaoEXgSk /mnt/boci/Music
```

Should now output:
```
[1/18] Checking: Space Song - First to Eleven
[✓] Found by ISRC: Space Song.flac
...
[18/18] Checking: The Pretender - First to Eleven
[✓] Found by ISRC: The Pretender.flac

All tracks present. Creating playlist: [Album Name].m3u8
Playlist created: [Album Name].m3u8
```

## Summary

✅ **Fixed:** Playlist creation now uses actual file paths from ISRC scan
✅ **Fixed:** Tracks found by ISRC are correctly identified as present
✅ **Fixed:** Playlist references actual filenames (not expected ones)
✅ **Tested:** Automated test confirms fix works correctly

The complete solution ensures that:
1. ISRC scan finds files with different names
2. Actual file paths are stored in `track.file_path`
3. Playlist creation uses these actual paths
4. Playlist is created successfully with all found tracks

## Files Changed
- `SpotiFLAC/SpotiFLAC.py` - 4 locations updated
  - Track dataclass: Added `file_path` field
  - Phase 1 match: Store file path
  - Phase 2 ISRC: Store file path
  - Playlist creation: Use stored file paths

## Security Analysis
- No security vulnerabilities introduced
- Only added a data field and used it consistently
- No external inputs affected
- CodeQL analysis: Not applicable (minor enhancement)

