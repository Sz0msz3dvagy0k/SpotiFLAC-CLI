# Building SpotiFLAC-CLI Linux Binaries

This guide provides comprehensive instructions for building SpotiFLAC-CLI as a standalone Linux binary.

## Table of Contents
- [Prerequisites](#prerequisites)
- [Quick Build](#quick-build)
- [Manual Build Instructions](#manual-build-instructions)
- [Platform-Specific Builds](#platform-specific-builds)
- [Testing the Binary](#testing-the-binary)
- [Troubleshooting](#troubleshooting)

## Prerequisites

### Required Software
- **Python**: Version 3.9 or higher
- **pip**: Python package installer
- **PyInstaller**: For creating standalone executables

### Installing Prerequisites on Linux

#### Ubuntu/Debian:
```bash
sudo apt update
sudo apt install python3 python3-pip
```

#### Fedora/RHEL/CentOS:
```bash
sudo dnf install python3 python3-pip
```

#### Arch Linux:
```bash
sudo pacman -S python python-pip
```

## Quick Build

Use the provided build script for the fastest way to build:

```bash
# Clone the repository
git clone https://github.com/Sz0msz3dvagy0k/SpotiFLAC-CLI.git
cd SpotiFLAC-CLI

# Run the build script
chmod +x build_linux.sh
./build_linux.sh
```

The binary will be created at `SpotiFLAC/dist/SpotiFLAC-Linux`

## Manual Build Instructions

### Step 1: Clone the Repository
```bash
git clone https://github.com/Sz0msz3dvagy0k/SpotiFLAC-CLI.git
cd SpotiFLAC-CLI
```

### Step 2: Install Python Dependencies
```bash
# Upgrade pip
python3 -m pip install --upgrade pip

# Install required dependencies
pip install pyinstaller certifi requests mutagen pyotp
```

### Step 3: Build the Binary
```bash
# Navigate to the SpotiFLAC directory
cd SpotiFLAC

# Build the standalone executable
pyinstaller --onefile --name SpotiFLAC-Linux --console ../launcher.py
```

### Step 4: Locate the Binary
The compiled binary will be located at:
```
SpotiFLAC/dist/SpotiFLAC-Linux
```

## Platform-Specific Builds

### x86_64 (64-bit Intel/AMD)

Standard build process works on x86_64 architecture:
```bash
cd SpotiFLAC
pyinstaller --onefile --name SpotiFLAC-Linux-x86_64 --console ../launcher.py
```

### ARM64 (64-bit ARM)

For ARM64 builds, you have two options:

#### Option 1: Build on ARM64 Hardware
If you're on an ARM64 machine (e.g., Raspberry Pi 4, AWS Graviton):
```bash
cd SpotiFLAC
pyinstaller --onefile --name SpotiFLAC-Linux-arm64 --console ../launcher.py
```

#### Option 2: Cross-compile using Docker
On an x86_64 machine with Docker and QEMU:
```bash
# Install QEMU for ARM emulation (Ubuntu/Debian)
sudo apt-get install qemu-user-static

# Build using Docker
docker run --rm --platform linux/arm64 \
  -v "$PWD":/workspace \
  -w /workspace python:3.12-bullseye \
  bash -c "
    pip install --upgrade pip && \
    pip install pyinstaller certifi requests mutagen pyotp && \
    cd SpotiFLAC && \
    pyinstaller --onefile --name SpotiFLAC-Linux-arm64 --console ../launcher.py
  "
```

## Testing the Binary

### Basic Functionality Test
```bash
# Make the binary executable
chmod +x SpotiFLAC/dist/SpotiFLAC-Linux

# Test with help command
./SpotiFLAC/dist/SpotiFLAC-Linux --help

# Test with a Spotify URL (replace with actual URL)
./SpotiFLAC/dist/SpotiFLAC-Linux "https://open.spotify.com/album/..." ./output --service tidal
```

### Verify Binary Information
```bash
# Check binary type
file SpotiFLAC/dist/SpotiFLAC-Linux

# Check binary dependencies (should be minimal)
ldd SpotiFLAC/dist/SpotiFLAC-Linux

# Check binary size
ls -lh SpotiFLAC/dist/SpotiFLAC-Linux
```

## Build Configuration Options

### PyInstaller Flags Explained
- `--onefile`: Bundle everything into a single executable
- `--name [NAME]`: Set the output binary name
- `--console`: Show console output (recommended for CLI tools)
- `../launcher.py`: Entry point script for the application

### Custom Build Options

#### Add an Icon (optional)
```bash
pyinstaller --onefile --name SpotiFLAC-Linux --console --icon=icon.ico ../launcher.py
```

#### Optimize for Size
```bash
pyinstaller --onefile --name SpotiFLAC-Linux --console --strip ../launcher.py
```

#### Debug Build
```bash
pyinstaller --onefile --name SpotiFLAC-Linux --console --debug all ../launcher.py
```

## Troubleshooting

### Issue: "ModuleNotFoundError" when running binary
**Solution**: Ensure all dependencies are installed when building:
```bash
pip install pyinstaller certifi requests mutagen pyotp
```

### Issue: Binary won't execute
**Solution**: Check permissions:
```bash
chmod +x SpotiFLAC/dist/SpotiFLAC-Linux
```

### Issue: "Permission denied" errors during build
**Solution**: Ensure you have write permissions in the directory:
```bash
sudo chown -R $USER:$USER .
```

### Issue: Large binary size
**Solution**: PyInstaller bundles Python interpreter and all dependencies. Typical size is 20-50 MB. To reduce:
```bash
pyinstaller --onefile --strip --console ../launcher.py
```

### Issue: Build fails on ARM64
**Solution**: Use Docker cross-compilation method or build on native ARM64 hardware.

## Distribution

### Creating a Release Package
```bash
# Create a tarball
cd SpotiFLAC/dist
tar -czvf SpotiFLAC-Linux-x86_64.tar.gz SpotiFLAC-Linux-x86_64

# Or create a zip file
zip SpotiFLAC-Linux-x86_64.zip SpotiFLAC-Linux-x86_64
```

### Verifying the Package
```bash
# Extract and test
tar -xzvf SpotiFLAC-Linux-x86_64.tar.gz
chmod +x SpotiFLAC-Linux-x86_64
./SpotiFLAC-Linux-x86_64 --help
```

## Automated Builds

This project includes GitHub Actions workflows for automated builds. See `.github/workflows/build-release.yml` for the CI/CD pipeline that automatically builds binaries for:
- Linux x86_64
- Linux ARM64
- Windows x86_64
- macOS x86_64

Releases are automatically created when version tags are pushed.

## Additional Resources

- [PyInstaller Documentation](https://pyinstaller.readthedocs.io/)
- [Project Repository](https://github.com/Sz0msz3dvagy0k/SpotiFLAC-CLI)
- [Python Packaging Guide](https://packaging.python.org/)

## License

This project is licensed under the terms specified in the LICENSE file.
