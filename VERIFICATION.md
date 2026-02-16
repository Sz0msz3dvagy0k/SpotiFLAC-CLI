# Verification: Check-Only Mode ISRC Scan Fix

## Issue Summary
In check-only mode with `--createplaylist`, tracks were being reported as missing even though they existed with slightly different filenames (due to filename sanitization differences like commas).

## Root Cause
The check-only early-exit logic was running **BEFORE** the ISRC scan code, which meant:
1. Exact filename check would fail (due to sanitization differences)
2. Code would immediately exit with "[✗] Missing" message
3. ISRC scan code was never reached
4. `track.downloaded` was never set to `True`
5. Playlist creation would fail thinking all files were missing

## Fix Verification

### Current Code Flow (CORRECT ✓)
Located in `SpotiFLAC/SpotiFLAC.py`, method `DownloadWorker.run()`, lines 683-713:

```python
# Phase 1: Quick filename check (lines 684-690)
if os.path.exists(new_filepath) and os.path.getsize(new_filepath) > 0:
    if self.check_only:
        update_progress(f"[✓] Found: {new_filename}")
    else:
        update_progress(f"File already exists: {new_filename}. Skipping download.")
    track.downloaded = True
    continue

# Phase 2: Smart ISRC scan (lines 692-708)
# *** This runs BEFORE check-only exit! ***
if track.isrc and (self.use_artist_subfolders or self.use_album_subfolders):
    existing_file, found_dir = check_isrc_in_artist_dirs(
        base_dir=self.outpath,
        artist_name=track.artists,
        isrc=track.isrc
    )
    if existing_file:
        track.downloaded = True
        if self.check_only:
            update_progress(f"[✓] Found by ISRC: {os.path.basename(existing_file)}")
        else:
            update_progress(
                f"File found by ISRC in {found_dir}: {os.path.basename(existing_file)}. Skipping download."
            )
        continue

# Phase 3: Check-only exit (lines 711-713)
# *** This happens AFTER ISRC scan! ***
if self.check_only:
    update_progress(f"[✗] Missing: {new_filename}")
    continue

# Phase 4: Download phase (lines 715+)
# Only reached if not in check-only mode
```

### Verification Results

**Test 1: Code Flow Order**
- ✅ Phase 1 (filename check): Line 684
- ✅ Phase 2 (ISRC scan): Line 694
- ✅ Phase 3 (check-only exit): Line 711
- ✅ **Correct order: ISRC scan happens BEFORE check-only exit**

**Test 2: Track.downloaded Flag**
- ✅ Phase 1 sets `track.downloaded = True` when exact filename found
- ✅ Phase 2 sets `track.downloaded = True` when ISRC match found
- ✅ Playlist creation can correctly identify which tracks exist

**Test 3: Check-Only Exit Behavior**
- ✅ Only prints "[✗] Missing" if file not found by either method
- ✅ Does not exit before trying ISRC scan

## Expected Behavior After Fix

When running:
```bash
SpotiFLAC-Linux --use-artist-subfolders --use-album-subfolders \
  --filename-format "{title}" --checkonly --createplaylist \
  https://open.spotify.com/album/... /path/to/music
```

The tool should:
1. Check for exact filename match
2. **If not found, scan for ISRC match before giving up**
3. Report "[✓] Found by ISRC: ..." for ISRC matches
4. Only report "[✗] Missing" if truly not found
5. Create playlist successfully if all tracks are found (by either method)

## Example Output (Expected)
```
[1/18] Checking: Space Song - First to Eleven
[✓] Found by ISRC: Space Song.flac
[2/18] Checking: DJ Got Us Fallin' In Love - First to Eleven
[✓] Found by ISRC: DJ Got Us Fallin' in Love.flac
...
[18/18] Checking: The Pretender - First to Eleven
[✓] Found by ISRC: The Pretender.flac

All tracks present. Creating playlist: Covers Vol. 18.m3u8
Playlist created successfully with 18 tracks.
```

## Implementation Status
✅ **Fix has been verified and is correctly implemented.**

The code structure ensures that ISRC scanning happens before check-only mode exits, allowing files with different filenames (but matching ISRC codes) to be correctly identified as present.

## Related
- Original fix implemented in PR #8: "Fix ISRC scanning to work in check-only mode"
- File: `SpotiFLAC/SpotiFLAC.py`
- Method: `DownloadWorker.run()`
- Lines: 683-713
