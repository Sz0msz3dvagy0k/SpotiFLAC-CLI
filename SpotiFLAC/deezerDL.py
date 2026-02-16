import requests
import asyncio
from mutagen.flac import FLAC
import os
import re
from typing import Optional, Tuple


def _check_isrc_exists(directory: str, isrc: str, artist_name: str = "") -> Tuple[Optional[str], bool]:
    """
    Check if a file with the given ISRC exists using artist-aware directory scanning.
    
    Args:
        directory: Base directory to search in
        isrc: ISRC code to match
        artist_name: Artist name to narrow down search (optional)
        
    Returns:
        Tuple of (file_path, found) where found is True if ISRC matches
    """
    if not isrc or not os.path.isdir(directory):
        return None, False
    
    # If no artist name provided, fall back to checking the current directory only
    if not artist_name:
        return _check_isrc_in_single_directory(directory, isrc)
    
    # Extract primary artist
    primary_artist = artist_name
    for separator in [" feat. ", " ft. ", " featuring ", ", ", " & ", " and "]:
        if separator in artist_name:
            primary_artist = artist_name.split(separator)[0].strip()
            break
    
    # Create regex pattern for matching artist directories
    artist_words = primary_artist.split()
    if not artist_words:
        return _check_isrc_in_single_directory(directory, isrc)
    
    # Build pattern that matches directories containing all artist name words
    pattern_parts = []
    for word in artist_words:
        escaped_word = re.escape(word)
        # Use word boundaries to avoid partial matches
        pattern_parts.append(f"(?=.*\\b{escaped_word}\\b)")
    
    pattern = "".join(pattern_parts)
    
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error:
        return _check_isrc_in_single_directory(directory, isrc)
    
    directories_to_check = [directory]
    
    # Find matching artist directories
    try:
        for entry in os.listdir(directory):
            entry_path = os.path.join(directory, entry)
            if os.path.isdir(entry_path):
                if regex.search(entry):
                    directories_to_check.append(entry_path)
                    # Check subdirectories (album folders)
                    try:
                        for subentry in os.listdir(entry_path):
                            subentry_path = os.path.join(entry_path, subentry)
                            if os.path.isdir(subentry_path):
                                directories_to_check.append(subentry_path)
                    except (OSError, PermissionError):
                        continue
        
        # Check compilation folders
        for folder in ["Various Artists", "Compilations", "VA", "Compilation"]:
            folder_path = os.path.join(directory, folder)
            if os.path.isdir(folder_path):
                directories_to_check.append(folder_path)
                try:
                    for subentry in os.listdir(folder_path):
                        subentry_path = os.path.join(folder_path, subentry)
                        if os.path.isdir(subentry_path):
                            directories_to_check.append(subentry_path)
                except (OSError, PermissionError):
                    continue
    except (OSError, PermissionError):
        pass
    
    # Check each directory for ISRC match
    for dir_to_check in directories_to_check:
        file_path, found = _check_isrc_in_single_directory(dir_to_check, isrc)
        if found and file_path:
            return file_path, True
    
    return None, False


def _check_isrc_in_single_directory(directory: str, isrc: str) -> Tuple[Optional[str], bool]:
    """Helper to check ISRC in a single directory."""
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


class DeezerDownloader:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        self.progress_callback = None

    def set_progress_callback(self, callback):
        self.progress_callback = callback

    def get_track_by_isrc(self, isrc):
        try:
            url = f"https://api.deezer.com/2.0/track/isrc:{isrc}"
            response = self.session.get(url)
            response.raise_for_status()

            data = response.json()

            if 'error' in data:
                print(f"Error from Deezer API: {data['error']['message']}")
                return None

            return data
        except requests.exceptions.RequestException as e:
            print(f"Error fetching track data: {e}")
            return None

    def extract_metadata(self, track_data):
        metadata = {}

        metadata['title'] = track_data.get('title', '')
        metadata['title_short'] = track_data.get('title_short', '')
        metadata['duration'] = track_data.get('duration', 0)
        metadata['track_position'] = track_data.get('track_position', 1)
        metadata['disk_number'] = track_data.get('disk_number', 1)
        metadata['isrc'] = track_data.get('isrc', '')
        metadata['release_date'] = track_data.get('release_date', '')
        metadata['explicit_lyrics'] = track_data.get('explicit_lyrics', False)

        if 'artist' in track_data:
            metadata['artist'] = track_data['artist'].get('name', '')
            metadata['artist_id'] = track_data['artist'].get('id', '')

        if 'contributors' in track_data:
            artists = []
            for contributor in track_data['contributors']:
                if contributor.get('role') == 'Main':
                    artists.append(contributor.get('name', ''))
            metadata['artists'] = ', '.join(artists) if artists else metadata.get('artist', '')

        if 'album' in track_data:
            album = track_data['album']
            metadata['album'] = album.get('title', '')
            metadata['album_id'] = album.get('id', '')
            metadata['cover_url'] = album.get('cover_xl', album.get('cover_big', ''))
            metadata['cover_md5'] = album.get('md5_image', '')

        metadata['deezer_link'] = track_data.get('link', '')
        metadata['preview_url'] = track_data.get('preview', '')

        return metadata

    def download_cover_art(self, cover_url, filename):
        if not cover_url:
            return None

        try:
            response = self.session.get(cover_url)
            response.raise_for_status()

            cover_path = f"{filename}_cover.jpg"
            with open(cover_path, 'wb') as f:
                f.write(response.content)

            return cover_path
        except Exception as e:
            print(f"Error downloading cover art: {e}")
            return None

    def embed_metadata(self, file_path, metadata, cover_path=None):
        try:
            audio = FLAC(file_path)

            audio.clear()

            if metadata.get('title'):
                audio['TITLE'] = metadata['title']
            if metadata.get('artists'):
                audio['ARTIST'] = metadata['artists']
            elif metadata.get('artist'):
                audio['ARTIST'] = metadata['artist']
            if metadata.get('album'):
                audio['ALBUM'] = metadata['album']
            if metadata.get('release_date'):
                audio['DATE'] = metadata['release_date']
            if metadata.get('track_position'):
                audio['TRACKNUMBER'] = str(metadata['track_position'])
            if metadata.get('disk_number'):
                audio['DISCNUMBER'] = str(metadata['disk_number'])
            if metadata.get('isrc'):
                audio['ISRC'] = metadata['isrc']

            if cover_path and os.path.exists(cover_path):
                with open(cover_path, 'rb') as f:
                    cover_data = f.read()

                from mutagen.flac import Picture
                picture = Picture()
                picture.type = 3
                picture.mime = 'image/jpeg'
                picture.desc = 'Cover'
                picture.data = cover_data
                audio.add_picture(picture)

            audio.save()
            print(f"Metadata embedded successfully in {file_path}")

        except Exception as e:
            print(f"Error embedding metadata: {e}")

    async def download_by_isrc(self, isrc, output_dir="."):
        print(f"Fetching track info for ISRC: {isrc}")

        track_data = self.get_track_by_isrc(isrc)
        if not track_data:
            print("Failed to get track data from Deezer API")
            return False

        metadata = self.extract_metadata(track_data)
        artist_name = metadata.get('artists', 'Unknown')
        print(f"Found track: {artist_name} - {metadata.get('title', 'Unknown')}")

        # Check if file with this ISRC already exists
        existing_file, exists = _check_isrc_exists(output_dir, isrc, artist_name)
        if exists and existing_file:
            print(f"File with ISRC {isrc} already exists: {existing_file}")
            return True

        track_id = track_data.get('id')
        if not track_id:
            print("No track ID found in Deezer API response")
            return False

        print(f"Using track ID: {track_id}")

        api_url = f"https://api.deezmate.com/dl/{track_id}"
        print(f"Requesting download links from: {api_url}")

        try:
            response = self.session.get(api_url)
            response.raise_for_status()
            api_data = response.json()

            if not api_data.get('success'):
                print("API request failed")
                return False

            links = api_data.get('links', {})
            flac_url = links.get('flac')

            if not flac_url:
                print("No FLAC download link found in API response")
                return False

            print(f"Successfully obtained FLAC download URL")

        except Exception as e:
            print(f"Error getting download URL from API: {e}")
            return False

        print("Downloading FLAC file...")
        try:
            response = self.session.get(flac_url)
            response.raise_for_status()

            safe_title = "".join(c for c in metadata.get('title', 'Unknown') if c.isalnum() or c in (' ', '-', '_')).rstrip()
            safe_artist = "".join(c for c in metadata.get('artists', 'Unknown') if c.isalnum() or c in (' ', '-', '_')).rstrip()
            filename = f"{safe_artist} - {safe_title}.flac"
            file_path = os.path.join(output_dir, filename)

            with open(file_path, 'wb') as f:
                f.write(response.content)

            downloaded = len(response.content)
            print(f"File size: {downloaded} bytes ({downloaded / (1024*1024):.2f} MB)")

            if self.progress_callback:
                self.progress_callback(downloaded, downloaded)

            print(f"Downloaded: {file_path}")

            cover_path = None
            if metadata.get('cover_url'):
                print("Downloading cover art...")
                cover_path = self.download_cover_art(metadata['cover_url'],
                                                   os.path.join(output_dir, f"{safe_artist} - {safe_title}"))

            print("Embedding metadata...")
            self.embed_metadata(file_path, metadata, cover_path)

            if cover_path and os.path.exists(cover_path):
                os.remove(cover_path)

            print(f"Successfully downloaded and tagged: {filename}")
            return True

        except Exception as e:
            print(f"Error downloading file: {e}")
            return False

async def main():
    print("=== DeezerDL - Deezer Downloader ===")
    downloader = DeezerDownloader()

    isrc = "USAT22409172"
    output_dir = "."

    success = await downloader.download_by_isrc(isrc, output_dir)
    if success:
        print("Download completed successfully!")
    else:
        print("Download failed!")

if __name__ == "__main__":
    try:
        import sys
        if sys.platform == "win32":
            import os
            os.system("chcp 65001 > nul")
            try:
                sys.stdout.reconfigure(encoding='utf-8')
            except:
                pass
    except:
        pass

    asyncio.run(main())