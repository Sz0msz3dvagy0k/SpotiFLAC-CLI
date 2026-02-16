#!/bin/bash
# Build script for SpotiFLAC-CLI Linux binaries
# This script automates the process of building a standalone Linux executable

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}====================================${NC}"
echo -e "${GREEN}SpotiFLAC-CLI Linux Build Script${NC}"
echo -e "${GREEN}====================================${NC}"
echo ""

# Check Python version
echo -e "${YELLOW}Checking Python version...${NC}"
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
REQUIRED_VERSION="3.9"

if ! python3 -c "import sys; exit(0 if sys.version_info >= (3, 9) else 1)" 2>/dev/null; then
    echo -e "${RED}Error: Python 3.9 or higher is required.${NC}"
    echo -e "${RED}Current version: ${PYTHON_VERSION}${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Python version: ${PYTHON_VERSION}${NC}"
echo ""

# Check if pip is available
echo -e "${YELLOW}Checking pip availability...${NC}"
if ! command -v pip &> /dev/null && ! command -v pip3 &> /dev/null; then
    echo -e "${RED}Error: pip is not installed.${NC}"
    echo -e "${YELLOW}Install it with: sudo apt install python3-pip${NC}"
    exit 1
fi

echo -e "${GREEN}✓ pip is available${NC}"
echo ""

# Detect architecture
ARCH=$(uname -m)
case $ARCH in
    x86_64)
        BUILD_NAME="SpotiFLAC-Linux-x86_64"
        ;;
    aarch64|arm64)
        BUILD_NAME="SpotiFLAC-Linux-arm64"
        ;;
    *)
        BUILD_NAME="SpotiFLAC-Linux"
        ;;
esac

echo -e "${YELLOW}Detected architecture: ${ARCH}${NC}"
echo -e "${YELLOW}Build name: ${BUILD_NAME}${NC}"
echo ""

# Install dependencies
echo -e "${YELLOW}Installing Python dependencies...${NC}"
python3 -m pip install --upgrade pip --quiet
pip install pyinstaller certifi requests mutagen pyotp --quiet

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Dependencies installed successfully${NC}"
else
    echo -e "${RED}Error: Failed to install dependencies${NC}"
    exit 1
fi
echo ""

# Change to SpotiFLAC directory
echo -e "${YELLOW}Building SpotiFLAC binary...${NC}"
cd SpotiFLAC

# Run PyInstaller
pyinstaller --onefile --name "$BUILD_NAME" --console ../launcher.py

if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}✓ Build completed successfully!${NC}"
    echo ""
    echo -e "${GREEN}====================================${NC}"
    echo -e "${GREEN}Build Summary${NC}"
    echo -e "${GREEN}====================================${NC}"
    echo -e "Binary location: ${GREEN}SpotiFLAC/dist/${BUILD_NAME}${NC}"
    echo -e "Binary size: ${GREEN}$(du -h dist/${BUILD_NAME} | cut -f1)${NC}"
    echo ""
    
    # Make binary executable
    chmod +x "dist/${BUILD_NAME}"
    
    echo -e "${YELLOW}To test the binary, run:${NC}"
    echo -e "  cd SpotiFLAC/dist"
    echo -e "  ./${BUILD_NAME} --help"
    echo ""
    echo -e "${YELLOW}For full usage instructions, see:${NC}"
    echo -e "  https://github.com/Sz0msz3dvagy0k/SpotiFLAC-CLI#readme"
    echo ""
else
    echo -e "${RED}Error: Build failed${NC}"
    exit 1
fi
