#!/usr/bin/env python3
"""
Launcher script for SpotiFLAC
"""

import sys
import os

# Add current directory to path to allow absolute imports
if getattr(sys, 'frozen', False):
    # Running as compiled executable
    application_path = sys._MEIPASS
else:
    # Running as script
    application_path = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, application_path)

# Now import and run the main SpotiFLAC module
if __name__ == '__main__':
    import spotiflac.SpotiFLAC
    spotiflac.SpotiFLAC.main()
