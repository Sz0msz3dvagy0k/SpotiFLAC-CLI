import os
import re
import time
import argparse
import asyncio
import unicodedata

from dataclasses import dataclass
from SpotiFLAC.getMetadata import get_filtered_data, parse_uri, SpotifyInvalidUrlException, get_track_lyrics
from SpotiFLAC.tidalDL import TidalDownloader
from SpotiFLAC.deezerDL import DeezerDownloader
from SpotiFLAC.qobuzDL import QobuzDownloader
from SpotiFLAC.amazonDL import AmazonDownloader
from mutagen.flac import FLAC

# Constants for artist folder matching
# These characters are treated as interchangeable separators in artist names
SEPARATOR_CHARS = '.-_'
SEPARATOR_PATTERN = r'[.\-_]'


@dataclass
class Config:
    url: str
    output_dir: str
    service: list = None
    filename_format: str = "{title} - {artist}"
    use_track_numbers: bool = False
    use_artist_subfolders: bool = False
    use_album_subfolders: bool = False
    embed_lyrics: bool = False
    check_only: bool = False
    create_playlist: bool = False
    is_album: bool = False
    is_playlist: bool = False
    is_single_track: bool = False
    album_or_playlist_name: str = ""
    tracks = []
    worker = None
    loop: int = 3600
    start_time: float = 0.0
    end_time: float = 0.0


@dataclass
class Track:
    external_urls: str
    title: str
    artists: str
    album: str
    track_number: int
    duration_ms: int
    id: str
    isrc: str = ""
    release_date: str = ""
    downloaded: bool = False
    file_path: str = ""  # Actual path to the downloaded/found file


def normalize_string(s: str) -> str:
    """
    Normalize Unicode string for consistent comparison.
    Uses NFKC normalization to handle various Unicode representations.
    
    Args:
        s: String to normalize
        
    Returns:
        Normalized string
    """
    if not s:
        return s
    return unicodedata.normalize('NFKC', s)


def extract_artist_variations(artist_name: str) -> list[str]:
    """
    Extract multiple variations of artist names for matching.
    
    Args:
        artist_name: Full artist string from track metadata
        
    Returns:
        List of artist name variations to try matching, ordered as follows:
        [0] Full artist string (always present)
        [1] If parentheses exist: content inside parentheses
            Otherwise: first artist from comma/separator split
        [2+] Additional variations (before-paren content, remaining artists, etc.)
        
        Examples:
        - "Olly Alexander (Years & Years)" -> ["Olly Alexander (Years & Years)", "Years & Years", "Olly Alexander"]
        - "League of Legends Music, TEYA" -> ["League of Legends Music, TEYA", "League of Legends Music", "TEYA"]
        - "R.A.D." -> ["R.A.D."]
    """
    variations = []
    
    if not artist_name:
        return variations
    
    # Normalize the string first
    artist_name = normalize_string(artist_name)
    
    # Always include the full artist name at index 0
    variations.append(artist_name)
    
    # Extract content in parentheses (e.g., "Years & Years" from "Olly Alexander (Years & Years)")
    # This is intentionally checked first so parenthetical content gets index 1
    parenthetical_match = re.search(r'\(([^)]+)\)', artist_name)
    if parenthetical_match:
        parenthetical_content = parenthetical_match.group(1).strip()
        if parenthetical_content:
            variations.append(parenthetical_content)  # Index 1 for parenthetical format
        # Add the part before parentheses at a later index
        # (e.g., "Olly Alexander" becomes index 2)
        before_paren = artist_name[:parenthetical_match.start()].strip()
        if before_paren:
            variations.append(before_paren)
    
    # Split by common separators and add individual artists
    # If no parentheses were found, the first split artist becomes index 1
    for separator in [", ", " feat. ", " ft. ", " featuring ", " & ", " and "]:
        if separator in artist_name:
            parts = artist_name.split(separator)
            for part in parts:
                part = part.strip()
                # Remove parenthetical content from individual parts
                part = re.sub(r'\s*\([^)]*\)', '', part).strip()
                if part and part not in variations:
                    variations.append(part)
            # Use only the first separator match
            break
    
    return variations


def check_isrc_in_artist_dirs(base_dir: str, artist_name: str, isrc: str) -> tuple[str | None, str | None]:
    """
    Check if a file with the given ISRC exists in artist-related directories.
    Uses a two-phase approach: quick filename check (handled by caller) then smart ISRC scan.
    
    Args:
        base_dir: Root directory to search in
        artist_name: Artist name from track metadata (e.g., "DJ Shadow, Cut Chemist")
        isrc: ISRC code to match
        
    Returns:
        Tuple of (full_path_to_file, directory_name) if found, or (None, None) if not found
    """
    if not isrc or not os.path.isdir(base_dir):
        return None, None
    
    # Get all artist name variations to try
    artist_variations = extract_artist_variations(artist_name)
    
    directories_to_check = []
    
    # Check root directory first (for flat structures)
    directories_to_check.append(base_dir)
    
    # Try matching with each artist variation
    for artist_variant in artist_variations:
        # Create regex pattern for matching artist directories
        # Handle special characters and various naming conventions
        artist_words = artist_variant.split()
        if not artist_words:
            continue
        
        # Build pattern that matches directories containing all artist name words
        # Example: "DJ Shadow" matches "DJ Shadow", "dj_shadow", "DJ-Shadow", etc.
        # Use custom boundaries instead of \b to handle special characters
        pattern_parts = []
        for word in artist_words:
            # Normalize the word
            word = normalize_string(word)
            
            # Replace dots, underscores, and hyphens with a pattern that matches any of them
            # This allows "R.A.D." to match "R.A.D_", "R-A-D", etc.
            # Build a flexible pattern character by character
            flexible_word = ""
            for char in word:
                if char in SEPARATOR_CHARS:
                    # Any of these characters can match each other
                    flexible_word += SEPARATOR_PATTERN
                else:
                    # Regular character - escape it for regex
                    flexible_word += re.escape(char)
            
            # Use custom boundaries that handle special characters
            # - Start of string or whitespace/underscore/hyphen/dot before word
            # - End of string or whitespace/underscore/hyphen/dot after word
            pattern_parts.append(f"(?=.*(?:^|[\\s._-]){flexible_word}(?:[\\s._-]|$))")
        
        # Combine into a single pattern (case-insensitive, matches all words in any order)
        pattern = "".join(pattern_parts)
        
        try:
            # Use re.UNICODE flag for proper Unicode support (Cyrillic, Japanese, etc.)
            regex = re.compile(pattern, re.IGNORECASE | re.UNICODE)
        except re.error:
            # If regex compilation fails, skip this variation
            continue
        
        # Find matching artist directories (limit depth to 2 levels)
        try:
            for entry in os.listdir(base_dir):
                entry_path = os.path.join(base_dir, entry)
                if os.path.isdir(entry_path):
                    # Normalize entry name for comparison
                    normalized_entry = normalize_string(entry)
                    
                    # Check if directory name matches artist pattern
                    if regex.search(normalized_entry):
                        if entry_path not in directories_to_check:
                            directories_to_check.append(entry_path)
                        # Also check subdirectories (album folders, etc.) - level 2
                        try:
                            for subentry in os.listdir(entry_path):
                                subentry_path = os.path.join(entry_path, subentry)
                                if os.path.isdir(subentry_path):
                                    if subentry_path not in directories_to_check:
                                        directories_to_check.append(subentry_path)
                        except (OSError, PermissionError):
                            continue
        except (OSError, PermissionError):
            pass
    
    # Also check common compilation folder names
    compilation_folders = ["Various Artists", "Compilations", "VA", "Compilation"]
    for folder in compilation_folders:
        folder_path = os.path.join(base_dir, folder)
        if os.path.isdir(folder_path):
            if folder_path not in directories_to_check:
                directories_to_check.append(folder_path)
            # Check album subfolders in compilation directories
            try:
                for subentry in os.listdir(folder_path):
                    subentry_path = os.path.join(folder_path, subentry)
                    if os.path.isdir(subentry_path):
                        if subentry_path not in directories_to_check:
                            directories_to_check.append(subentry_path)
            except (OSError, PermissionError):
                continue
    
    # Check each directory for ISRC match
    for directory in directories_to_check:
        file_path, found = _check_isrc_in_directory(directory, isrc)
        if found and file_path:
            # Return the file path and the parent directory name for logging
            parent_dir = os.path.basename(os.path.dirname(file_path))
            if not parent_dir or parent_dir == os.path.basename(base_dir):
                parent_dir = "root"
            return file_path, parent_dir
    
    return None, None


def _check_isrc_in_directory(directory: str, isrc: str) -> tuple[str | None, bool]:
    """
    Helper function to check for ISRC in a single directory.
    
    Args:
        directory: Directory to scan for FLAC files
        isrc: ISRC code to match
        
    Returns:
        Tuple of (file_path, found) where found is True if ISRC matches
    """
    if not isrc or not os.path.isdir(directory):
        return None, False
    
    try:
        for entry in os.listdir(directory):
            if not entry.lower().endswith(".flac"):
                continue
            path = os.path.join(directory, entry)
            try:
                audio = FLAC(path)
                if "ISRC" in audio and audio["ISRC"] and audio["ISRC"][0] == isrc:
                    return path, True
            except Exception:
                continue
    except (OSError, PermissionError):
        pass
    
    return None, False


def get_metadata(url):
    try:
        metadata = get_filtered_data(url)
        if "error" in metadata:
            print("Error fetching metadata:", metadata["error"])
        else:
            print("Metadata fetched successfully.")
            return metadata
    except SpotifyInvalidUrlException as e:
        print("Invalid URL:", str(e))
    except Exception as e:
        print("An error occurred while fetching metadata:", str(e))


def fetch_tracks(url):
    if not url:
        print('Warning: Please enter a Spotify URL.')
        return

    try:
        print('Just a moment. Fetching metadata...')

        metadata = get_metadata(url)
        on_metadata_fetched(metadata)

    except Exception as e:
        print(f'Error: Failed to start metadata fetch: {str(e)}')


def on_metadata_fetched(metadata):
    try:
        url_info = parse_uri(config.url)

        if url_info["type"] == "track":
            handle_track_metadata(metadata["track"])
        elif url_info["type"] == "album":
            handle_album_metadata(metadata)
        elif url_info["type"] == "playlist":
            handle_playlist_metadata(metadata)

    except Exception as e:
        print(f'Error: {str(e)}')


def handle_track_metadata(track_data):
    track_id = track_data["external_urls"].split("/")[-1]

    if any(t.id == track_id for t in config.tracks):
        return

    track = Track(
        external_urls=track_data["external_urls"],
        title=track_data["name"],
        artists=track_data["artists"],
        album=track_data["album_name"],
        track_number=1,
        duration_ms=track_data.get("duration_ms", 0),
        id=track_id,
        isrc=track_data.get("isrc", ""),
        release_date=track_data.get("release_date", "")
    )

    config.tracks = [track]
    config.is_single_track = True
    config.is_album = config.is_playlist = False
    config.album_or_playlist_name = f"{config.tracks[0].title} - {config.tracks[0].artists}"


def handle_album_metadata(album_data):
    config.album_or_playlist_name = album_data["album_info"]["name"]
    album_release_date = album_data["album_info"].get("release_date", "")

    for track in album_data["track_list"]:
        track_id = track["external_urls"].split("/")[-1]

        if any(t.id == track_id for t in config.tracks):
            continue

        config.tracks.append(Track(
            external_urls=track["external_urls"],
            title=track["name"],
            artists=track["artists"],
            album=config.album_or_playlist_name,
            track_number=track["track_number"],
            duration_ms=track.get("duration_ms", 0),
            id=track_id,
            isrc=track.get("isrc", ""),
            release_date=track.get("release_date", album_release_date)
        ))

    config.is_album = True
    config.is_playlist = config.is_single_track = False


def handle_playlist_metadata(playlist_data):
    config.album_or_playlist_name = playlist_data["playlist_info"]["owner"]["name"]

    for track in playlist_data["track_list"]:
        track_id = track["external_urls"].split("/")[-1]

        if any(t.id == track_id for t in config.tracks):
            continue

        config.tracks.append(Track(
            external_urls=track["external_urls"],
            title=track["name"],
            artists=track["artists"],
            album=track["album_name"],
            track_number=track.get("track_number", len(config.tracks) + 1),
            duration_ms=track.get("duration_ms", 0),
            id=track_id,
            isrc=track.get("isrc", ""),
            release_date=track.get("release_date", "")
        ))

    config.is_playlist = True
    config.is_album = config.is_single_track = False


def download_tracks(indices):
    raw_outpath = config.output_dir
    outpath = os.path.normpath(raw_outpath)
    if not os.path.exists(outpath):
        print('Warning: Invalid output directory. Please check if the folder exists.')
        return

    tracks_to_download = config.tracks if config.is_single_track else [config.tracks[i] for i in indices]

    # Only create album/playlist folder if NOT using artist/album subfolders
    # When subfolders are enabled, DownloadWorker handles the structure
    if config.is_album or config.is_playlist:
        if not config.use_artist_subfolders and not config.use_album_subfolders:
            name = config.album_or_playlist_name.strip()
            folder_name = name
            outpath = os.path.join(outpath, folder_name)
            os.makedirs(outpath, exist_ok=True)

    try:
        start_download_worker(tracks_to_download, outpath)
    except Exception as e:
        print(f"Error: An error occurred while starting the download: {str(e)}")


def start_download_worker(tracks_to_download, outpath):
    config.worker = DownloadWorker(
        tracks_to_download,
        outpath,
        config.is_single_track,
        config.is_album,
        config.is_playlist,
        config.album_or_playlist_name,
        config.filename_format,
        config.use_track_numbers,
        config.use_artist_subfolders,
        config.use_album_subfolders,
        config.service,
        config.embed_lyrics,
        config.check_only,
        config.create_playlist,
    )
    config.worker.run()


def on_download_finished(success, message, failed_tracks, total_elapsed=None):
    if success:
        print(f"\n=======================================")
        print(f"\nStatus: {message}")
        if failed_tracks:
            print("\nFailed downloads:")
            for title, artists, error in failed_tracks:
                print(f"• {title} - {artists}")
                print(f"  Error: {error}\n")
    else:
        print(f"Error: {message}")

    if total_elapsed is not None:
        print(f"\nElapsed time for this download loop: {format_seconds(total_elapsed)}")

    if config.loop is not None:
        print(f"\nDownload starting again in: {format_minutes(config.loop)}")
        print(f"\n=======================================")
        time.sleep(config.loop * 60)
        fetch_tracks(config.url)
        download_tracks(range(len(config.tracks)))


def update_progress(message):
    print(message)


def format_minutes(minutes):
    if minutes < 60:
        return f"{minutes} minutes"
    elif minutes < 1440:
        hours = minutes // 60
        mins = minutes % 60
        return f"{hours} hours {mins} minutes"
    else:
        days = minutes // 1440
        hours = (minutes % 1440) // 60
        mins = minutes % 60
        return f"{days} days {hours} hours {mins} minutes"


def format_seconds(seconds: float) -> str:
    seconds = int(round(seconds))

    days, rem = divmod(seconds, 86400)
    hrs, rem = divmod(rem, 3600)
    mins, secs = divmod(rem, 60)

    parts = []
    if days:
        parts.append(f"{days}d")
    if hrs:
        parts.append(f"{hrs}h")
    if mins:
        parts.append(f"{mins}m")
    if secs or not parts:
        parts.append(f"{secs}s")

    return " ".join(parts)


def sanitize_filename_component(value: str) -> str:
    """Normalize whitespace in filename components"""
    if not value:
        return ""
    # Only normalize whitespace, keep all special characters
    normalized = re.sub(r'\s+', ' ', value).strip()
    return normalized


def format_custom_filename(template: str, track, position: int = 1) -> str:
    year = ""
    if track.release_date:
        year = track.release_date.split("-")[0] if "-" in track.release_date else track.release_date

    duration = ""
    if track.duration_ms:
        total_seconds = track.duration_ms // 1000
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        duration = f"{minutes:02d}:{seconds:02d}"

    replacements = {
        "title": sanitize_filename_component(track.title),
        "artist": sanitize_filename_component(track.artists),
        "album": sanitize_filename_component(track.album),
        "track_number": f"{track.track_number:02d}" if track.track_number else f"{position:02d}",
        "track": f"{track.track_number:02d}" if track.track_number else f"{position:02d}",
        "date": sanitize_filename_component(track.release_date),
        "year": year,
        "position": f"{position:02d}",
        "isrc": sanitize_filename_component(track.isrc),
        "duration": duration,
    }

    result = template
    for key, value in replacements.items():
        result = result.replace(f"{{{key}}}", value)

    if not result.lower().endswith('.flac'):
        result += '.flac'

    result = re.sub(r'\s+', ' ', result).strip()

    return result


def detect_various_artists_album(tracks, album_name):
    """
    Detect if an album has multiple artists (compilation/various artists album).
    Returns True if album should be placed in Various Artists folder.
    
    Args:
        tracks: List of Track objects
        album_name: Name of the album to check
        
    Returns:
        bool: True if multiple artists detected for this album
    """
    if not tracks or not album_name:
        return False
    
    # Get all tracks for this specific album
    album_tracks = [t for t in tracks if t.album == album_name]
    
    if len(album_tracks) <= 1:
        return False
    
    # Get unique artists, filtering out None, non-string, and empty/whitespace values
    unique_artists = set(
        stripped for t in album_tracks 
        if isinstance(t.artists, str) and (stripped := t.artists.strip())
    )
    
    # If more than one unique artist for this album, it's a various artists album
    return len(unique_artists) > 1


def create_m3u8_playlist(worker, check_only=False):
    """
    Create an M3U8 playlist file from the tracks.
    
    Args:
        worker: DownloadWorker instance with tracks and settings
        check_only: If True, only create playlist if all tracks exist
        
    Returns:
        bool: True if playlist was created, False otherwise
    """
    # Only create playlists for albums and playlists, not single tracks
    if worker.is_single_track:
        return False
    
    if not (worker.is_album or worker.is_playlist):
        return False
    
    # Use playlist name as-is
    playlist_name = worker.album_or_playlist_name.strip()
    playlist_filename = f"{playlist_name}.m3u8"
    playlist_path = os.path.join(worker.outpath, playlist_filename)
    
    # Pre-populate various artists cache if using both subfolders
    if worker.use_artist_subfolders and worker.use_album_subfolders:
        unique_albums = set(track.album for track in worker.tracks if track.album)
        for album in unique_albums:
            if album not in worker._various_artists_cache:
                worker._various_artists_cache[album] = detect_various_artists_album(worker.tracks, album)
    
    # Build track file paths
    track_files = []
    missing_count = 0
    
    for i, track in enumerate(worker.tracks):
        # If track has a stored file_path (from exact match or ISRC scan), use it
        # This ensures playlist references the actual file location, not the expected one
        if track.file_path and os.path.exists(track.file_path):
            filepath = track.file_path
            file_exists = True
        else:
            # Otherwise, construct the expected path based on format settings
            # This fallback is used when tracks haven't been checked/downloaded yet
            track_outpath = worker.outpath
            
            if worker.use_artist_subfolders:
                if worker.use_album_subfolders:
                    if worker._various_artists_cache.get(track.album, False):
                        artist_folder = "Various Artists"
                    else:
                        artist_folder = worker.get_sanitized_artist_folder(track)
                else:
                    artist_folder = worker.get_sanitized_artist_folder(track)
                track_outpath = os.path.join(track_outpath, artist_folder)
            
            if worker.use_album_subfolders:
                album_folder = track.album
                track_outpath = os.path.join(track_outpath, album_folder)
            
            # Use track's own track number, fallback to position in list
            position = track.track_number if track.track_number else i + 1
            filename = worker.get_formatted_filename(track, position)
            filepath = os.path.join(track_outpath, filename)
            
            # Check if file exists
            file_exists = os.path.exists(filepath)
        
        # Count missing files
        if not file_exists:
            missing_count += 1
        
        # Build relative path from playlist location to track file
        rel_path = os.path.relpath(filepath, worker.outpath)
        
        # Calculate duration in seconds (use 0 for unknown duration)
        duration = track.duration_ms // 1000 if track.duration_ms else 0
        
        track_files.append({
            'path': rel_path,
            'duration': duration,
            'title': track.title,
            'artist': track.artists,
            'exists': file_exists
        })
    
    # If check_only mode and files are missing, don't create playlist
    if check_only and missing_count > 0:
        total_tracks = len(track_files)
        update_progress(f"\nPlaylist incomplete. Missing {missing_count} of {total_tracks} tracks. Playlist not created.")
        return False
    
    # If check_only mode and all files exist, create playlist
    if check_only:
        update_progress(f"\nAll tracks present. Creating playlist: {playlist_filename}")
    
    # Write M3U8 file
    try:
        with open(playlist_path, 'w', encoding='utf-8') as f:
            f.write("#EXTM3U\n")
            for track_info in track_files:
                f.write(f"#EXTINF:{track_info['duration']},{track_info['artist']} - {track_info['title']}\n")
                f.write(f"{track_info['path']}\n")
        
        update_progress(f"\nPlaylist created: {playlist_filename}")
        return True
    except Exception as e:
        update_progress(f"\n[!] Warning: Failed to create playlist: {e}")
        return False


class DownloadWorker:
    def __init__(self, tracks, outpath, is_single_track=False, is_album=False, is_playlist=False,
                 album_or_playlist_name='', filename_format='{title} - {artist}', use_track_numbers=True,
                 use_artist_subfolders=False, use_album_subfolders=False, services=["tidal"], 
                 embed_lyrics=False, check_only=False, create_playlist=False):
        super().__init__()
        self.tracks = tracks
        self.outpath = outpath
        self.is_single_track = is_single_track
        self.is_album = is_album
        self.is_playlist = is_playlist
        self.album_or_playlist_name = album_or_playlist_name
        self.filename_format = filename_format
        self.use_track_numbers = use_track_numbers
        self.use_artist_subfolders = use_artist_subfolders
        self.use_album_subfolders = use_album_subfolders
        self.services = services
        self.embed_lyrics = embed_lyrics
        self.check_only = check_only
        self.create_playlist = create_playlist
        self.failed_tracks = []
        self._various_artists_cache = {}

    def get_formatted_filename(self, track, position=1):
        if self.filename_format in ["title_artist", "artist_title", "title_only"]:
            if self.filename_format == "artist_title":
                filename = f"{track.artists} - {track.title}.flac"
            elif self.filename_format == "title_only":
                filename = f"{track.title}.flac"
            else:
                filename = f"{track.title} - {track.artists}.flac"
            return filename

        return format_custom_filename(self.filename_format, track, position)

    def get_sanitized_artist_folder(self, track):
        """
        Extract and sanitize the artist name for folder creation.
        Uses the first artist variation from extract_artist_variations() for consistency.
        
        Args:
            track: Track object containing artist information
            
        Returns:
            str: Sanitized folder name for the artist, or "Unknown Artist" if invalid
        """
        # Handle None or non-string artist values
        if not track.artists or not isinstance(track.artists, str):
            return "Unknown Artist"
        
        # Get artist variations from extract_artist_variations()
        # See that function's docstring for detailed ordering explanation
        variations = extract_artist_variations(track.artists)
        
        # Use variations[1] when available, which provides the most appropriate folder name:
        # - For "Olly Alexander (Years & Years)" -> "Years & Years" (parenthetical content)
        # - For "League of Legends Music, TEYA" -> "League of Legends Music" (first artist)
        # - For "R.A.D." -> "R.A.D." (only variations[0] exists, use that)
        if len(variations) > 1:
            artist_name = variations[1]
        else:
            artist_name = variations[0] if variations else track.artists
        
        return artist_name

    def run(self):
        try:

            total_tracks = len(self.tracks)

            start = time.perf_counter()

            def progress_update(current, total):
                if total <= 0:
                    update_progress("Processing metadata...")

            for i, track in enumerate(self.tracks):

                if track.downloaded:
                    continue

                # In check-only mode, use a different message
                if self.check_only:
                    update_progress(f"[{i + 1}/{total_tracks}] Checking: {track.title} - {track.artists}")
                else:
                    update_progress(f"[{i + 1}/{total_tracks}] Starting download: {track.title} - {track.artists}")

                track_outpath = self.outpath

                if self.use_artist_subfolders:
                    if self.use_album_subfolders:
                        if track.album not in self._various_artists_cache:
                            self._various_artists_cache[track.album] = detect_various_artists_album(self.tracks, track.album)
                        
                        if self._various_artists_cache[track.album]:
                            artist_folder = "Various Artists"
                        else:
                            artist_folder = self.get_sanitized_artist_folder(track)
                    else:
                        artist_folder = self.get_sanitized_artist_folder(track)
                    track_outpath = os.path.join(track_outpath, artist_folder)

                if self.use_album_subfolders:
                    album_folder = track.album
                    track_outpath = os.path.join(track_outpath, album_folder)

                os.makedirs(track_outpath, exist_ok=True)

                new_filename = self.get_formatted_filename(track, i + 1)
                new_filepath = os.path.join(track_outpath, new_filename)

                # Phase 1: Quick filename check
                if os.path.exists(new_filepath) and os.path.getsize(new_filepath) > 0:
                    if self.check_only:
                        update_progress(f"[✓] Found: {new_filename}")
                    else:
                        update_progress(f"File already exists: {new_filename}. Skipping download.")
                    track.downloaded = True
                    track.file_path = new_filepath  # Store the actual file path
                    continue

                # Phase 2: Smart ISRC scan in artist directories (only if Phase 1 fails)
                # This runs in BOTH check-only and download modes
                if track.isrc and (self.use_artist_subfolders or self.use_album_subfolders):
                    existing_file, found_dir = check_isrc_in_artist_dirs(
                        base_dir=self.outpath,
                        artist_name=track.artists,
                        isrc=track.isrc
                    )
                    if existing_file:
                        track.downloaded = True
                        track.file_path = existing_file  # Store the actual file path found by ISRC
                        if self.check_only:
                            update_progress(f"[✓] Found by ISRC: {os.path.basename(existing_file)}")
                        else:
                            update_progress(
                                f"File found by ISRC in {found_dir}: {os.path.basename(existing_file)}. Skipping download."
                            )
                        continue
                
                # If in check-only mode and file doesn't exist, mark as missing and continue
                if self.check_only:
                    update_progress(f"[✗] Missing: {new_filename}")
                    continue

                download_success = False
                last_error = None

                for svc in self.services:
                    update_progress(f"Trying service: {svc}")

                    if svc == "tidal":
                        downloader = TidalDownloader(check_only=self.check_only)
                    elif svc == "deezer":
                        downloader = DeezerDownloader()
                    elif svc == "qobuz":
                        downloader = QobuzDownloader()
                    elif svc == "amazon":
                        downloader = AmazonDownloader()
                    else:
                        downloader = TidalDownloader(check_only=self.check_only)

                    downloader.set_progress_callback(progress_update)

                    try:
                        if not track.isrc:
                            raise Exception("No ISRC available")

                        if svc == "tidal":
                            update_progress(
                                f"Searching and downloading from Tidal for ISRC: {track.isrc} - {track.title} - {track.artists}"
                            )

                            result = downloader.download(
                                query=track.title,
                                artist_name=track.artists,
                                isrc=track.isrc,
                                output_dir=track_outpath,
                                quality="LOSSLESS",
                            )

                            if isinstance(result, str) and os.path.exists(result):
                                downloaded_file = result

                            elif isinstance(result, dict) and result.get("success") == False:
                                if result.get("error") == "Download stopped by user":
                                    update_progress(f"Download stopped by user for: {track.title}")
                                    return
                                raise Exception(result.get("error", "Tidal download failed"))

                            elif isinstance(result, dict) and result.get("status") in ("all_skipped", "skipped_exists"):
                                downloaded_file = new_filepath

                            else:
                                raise Exception(f"Unexpected Tidal result: {result}")

                        elif svc == "deezer":
                            update_progress(f"Downloading from Deezer with ISRC: {track.isrc}")

                            ok = asyncio.run(downloader.download_by_isrc(track.isrc, track_outpath))

                            if not ok:
                                raise Exception("Deezer download failed")

                            import glob
                            flac_files = glob.glob(os.path.join(track_outpath, "*.flac"))
                            if not flac_files:
                                raise Exception("No FLAC file found after Deezer download")

                            downloaded_file = max(flac_files, key=os.path.getctime)

                        elif svc == "qobuz":
                            update_progress(f"Downloading from Qobuz with ISRC: {track.isrc}")

                            qb_format = "title-artist"
                            downloaded_file = downloader.download_by_isrc(
                                isrc=track.isrc,
                                output_dir=track_outpath,
                                quality="LOSSLESS",
                                filename_format=qb_format,
                                include_track_number=self.use_track_numbers,
                                position=track.track_number or i + 1,
                                spotify_track_name=track.title,
                                spotify_artist_name=track.artists,
                                spotify_album_name=track.album,
                                use_album_track_number=self.use_track_numbers,
                            )

                        elif svc == "amazon":
                            update_progress(f"Downloading from Amazon Music for track ID: {track.id}")
                            amz_format = "title-artist"
                            downloaded_file = downloader.download_by_spotify_id(
                                spotify_track_id=track.id,
                                output_dir=track_outpath,
                                filename_format=amz_format,
                                include_track_number=self.use_track_numbers,
                                position=track.track_number or i + 1,
                                spotify_track_name=track.title,
                                spotify_artist_name=track.artists,
                                spotify_album_name=track.album,
                                use_album_track_number=self.use_track_numbers,
                            )

                        else:
                            track_id = track.id
                            update_progress(f"Getting track info for ID: {track_id} from {svc}")

                            try:
                                loop = asyncio.get_event_loop()
                                if loop.is_closed():
                                    loop = asyncio.new_event_loop()
                                    asyncio.set_event_loop(loop)
                            except RuntimeError:
                                loop = asyncio.new_event_loop()
                                asyncio.set_event_loop(loop)

                            metadata = loop.run_until_complete(
                                downloader.get_track_info(track_id, svc)
                            )

                            downloaded_file = downloader.download(metadata, track_outpath)

                        if downloaded_file and os.path.exists(downloaded_file):
                            if downloaded_file != new_filepath:
                                try:
                                    os.rename(downloaded_file, new_filepath)
                                    update_progress(f"File renamed to: {new_filename}")
                                except OSError as e:
                                    update_progress(
                                        f"[X] Warning: Could not rename file {downloaded_file} → {new_filepath}: {e}"
                                    )
                            update_progress(f"Successfully downloaded using: {svc}")
                            track.downloaded = True
                            track.file_path = new_filepath  # Store the actual file path
                            download_success = True
                            
                            # Embed lyrics if requested
                            if self.embed_lyrics:
                                try:
                                    update_progress(f"Fetching lyrics for: {track.title}")
                                    
                                    lyrics = get_track_lyrics(track.id)
                                    
                                    if lyrics:
                                        audio = FLAC(new_filepath)
                                        audio['LYRICS'] = lyrics
                                        audio.save()
                                        update_progress(f"Embedded lyrics for: {track.title}")
                                    else:
                                        update_progress(f"No lyrics available for: {track.title}")
                                except Exception as e:
                                    update_progress(f"[!] Warning: Failed to embed lyrics: {e}")
                                    # Don't fail the download if lyrics embedding fails
                            
                            break

                        else:
                            raise Exception("Downloaded file missing or invalid")

                    except Exception as e:
                        last_error = str(e)
                        update_progress(f"[X] {svc} failed: {e}")
                        continue

                if not download_success:
                    self.failed_tracks.append((track.title, track.artists, last_error))
                    update_progress(f"[X] Failed all services for: {track.title}")
                    continue

            total_elapsed = time.perf_counter() - start

            # Create M3U8 playlist if requested
            if self.create_playlist:
                create_m3u8_playlist(self, self.check_only)

            msg = "Download completed!" if not self.check_only else "Check completed!"
            if self.failed_tracks:
                msg += f"\n\nFailed downloads: {len(self.failed_tracks)}"

            on_download_finished(True, msg, self.failed_tracks, total_elapsed)

        except Exception as e:
            total_elapsed = time.perf_counter() - start
            on_download_finished(False, str(e), self.failed_tracks, total_elapsed)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("url", help="Spotify URL")
    parser.add_argument("output_dir", help="Output directory")
    parser.add_argument(
        "--service",
        choices=["tidal", "deezer", "qobuz", "amazon"],
        nargs="+",
        default=["tidal"],
        help="One or more services to try in order",
    )
    parser.add_argument(
        "--filename-format",
        default="{title} - {artist}",
        help='Custom filename format using placeholders (e.g., "{title}, {artist}, {album}, {track_number}, {date}, {year}, {isrc}, {duration}")'
    )
    parser.add_argument("--use-track-numbers", action="store_true", help="(Deprecated - use {track} in format)")
    parser.add_argument("--use-artist-subfolders", action="store_true")
    parser.add_argument("--use-album-subfolders", action="store_true")
    parser.add_argument("--embed-lyrics", action="store_true", help="Embed lyrics into FLAC files")
    parser.add_argument("--checkonly", action="store_true", help="Check if songs exist without downloading")
    parser.add_argument("--createplaylist", action="store_true", help="Create M3U8 playlist file from album/playlist")
    parser.add_argument("--loop", type=int, help="Loop delay in minutes")
    return parser.parse_args()


def SpotiFLAC(
        url: str,
        output_dir: str,
        services=["tidal", "deezer", "qobuz", "amazon"],
        filename_format="{title} - {artist}",
        use_track_numbers=False,
        use_artist_subfolders=False,
        use_album_subfolders=False,
        embed_lyrics=False,
        check_only=False,
        create_playlist=False,
        loop=None
):
    global config
    config = Config(
        url=url,
        output_dir=output_dir,
        service=services,
        filename_format=filename_format,
        use_track_numbers=use_track_numbers,
        use_artist_subfolders=use_artist_subfolders,
        use_album_subfolders=use_album_subfolders,
        embed_lyrics=embed_lyrics,
        check_only=check_only,
        create_playlist=create_playlist,
        loop=loop
    )

    try:
        fetch_tracks(config.url)
        download_tracks(range(len(config.tracks)))
    except KeyboardInterrupt:
        print("\nDownload stopped by user.")


def main():
    args = parse_args()
    SpotiFLAC(
        url=args.url,
        output_dir=args.output_dir,
        services=args.service,
        filename_format=args.filename_format,
        use_track_numbers=args.use_track_numbers,
        use_artist_subfolders=args.use_artist_subfolders,
        use_album_subfolders=args.use_album_subfolders,
        embed_lyrics=args.embed_lyrics,
        check_only=args.checkonly,
        create_playlist=args.createplaylist,
        loop=args.loop
    )


if __name__ == "__main__":
    main()