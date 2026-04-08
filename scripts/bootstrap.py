#!/usr/bin/env python3
"""
Bootstrap script for Oracle MCP Server: Python check, dependencies, editable install, config copy.
"""

import json
import subprocess
import sys
from pathlib import Path


def get_repository_root() -> Path:
    """Directory containing pyproject.toml (parent of scripts/)."""
    return Path(__file__).resolve().parent.parent


def check_python_version():
    """Check if Python version is compatible"""
    if sys.version_info < (3, 8):
        print("❌ Python 3.8 or higher is required")
        sys.exit(1)
    print(f"✅ Python {sys.version_info.major}.{sys.version_info.minor} detected")


def install_dependencies(repository_root: Path):
    """Install Python dependencies from requirements.txt"""
    print("📦 Installing Python dependencies...")
    requirements_file = repository_root / "requirements.txt"
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-r", str(requirements_file)]
        )
        print("✅ Dependencies installed successfully")
    except subprocess.CalledProcessError as install_error:
        print(f"❌ Failed to install dependencies: {install_error}")
        sys.exit(1)


def install_editable_package(repository_root: Path):
    """Install the package in editable mode so `python -m oracle_mcp_server` works."""
    print("📦 Installing package in editable mode...")
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-e", str(repository_root)]
        )
        print("✅ Editable install completed")
    except subprocess.CalledProcessError as install_error:
        print(f"❌ Editable install failed: {install_error}")
        sys.exit(1)


def create_config(repository_root: Path):
    """Create config.json from example if it doesn't exist"""
    config_file = repository_root / "config.json"
    example_file = repository_root / "config" / "config.example.json"

    if config_file.exists():
        print("✅ config.json already exists")
        return

    if not example_file.exists():
        print("❌ config/config.example.json not found")
        sys.exit(1)

    print("📝 Creating config.json from example...")
    try:
        with open(example_file, 'r', encoding="utf-8") as example_handle:
            config = json.load(example_handle)

        with open(config_file, 'w', encoding="utf-8") as config_handle:
            json.dump(config, config_handle, indent=4)

        print("✅ config.json created successfully")
        print("⚠️  Please edit config.json with your database credentials")
    except Exception as create_error:
        print(f"❌ Failed to create config.json: {create_error}")
        sys.exit(1)


def check_oracle_client():
    """Check if Oracle client is available"""
    print("🔍 Checking Oracle client availability...")
    try:
        import oracledb  # noqa: F401
        print("✅ Oracle Python driver (oracledb) is available")
    except ImportError:
        print("❌ Oracle Python driver not found")
        print("💡 Install with: pip install oracledb[thick]")
        print("💡 Or install Oracle Instant Client and add to PATH")


def main():
    """Main setup function"""
    repository_root = get_repository_root()

    print("🚀 Setting up Oracle MCP Server...")
    print("=" * 50)

    check_python_version()
    install_dependencies(repository_root)
    install_editable_package(repository_root)
    create_config(repository_root)
    check_oracle_client()

    print("=" * 50)
    print("✅ Setup completed!")
    print("📝 Next steps:")
    print("   1. Edit config.json with your database credentials")
    print("   2. Install Oracle Client Libraries if not already installed")
    print("   3. Run: python -m oracle_mcp_server")
    print("   4. Configure your MCP client to use this server")


if __name__ == "__main__":
    main()
