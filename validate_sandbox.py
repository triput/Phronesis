# ==============================================================================
# File: f:/Code Repo/Phronesis_Django/validate_sandbox.py
# Description: Automated environment verification script for cloud sandbox instances
# Component: DevOps / Tooling
# Version: 1.0 (Gold Master)
# Created: 2026-06-26
# Last Update: 2026-06-26
# ==============================================================================
"""Automated sandbox environment validation utility.

Checks system runtimes, critical environment variables, network loops, 
and workspace dependencies to ensure the AI agent has a stable execution context.
"""

import os
import sys
import shutil
import subprocess

def check_runtime(binary_name: str) -> bool:
    """Check if a specific system binary is accessible in the PATH."""
    path = shutil.which(binary_name)
    if path:
        print(f"  [✓] {binary_name} found at: {path}", file=sys.stdout)
        return True
    print(f"  [✗] {binary_name} is MISSING from system PATH.", file=sys.stderr)
    return False

def main():
    print("==================================================")
    print("  ANTIGRAVITY SANDBOX ENVIRONMENT VALIDATION       ")
    print("==================================================\n")
    
    errors = 0

    # 1. Check Core Executables
    print("--- Checking System Runtimes ---")
    required_binaries = ["python3", "git", "pip3"]
    for binary in required_binaries:
        if not check_runtime(binary):
            errors += 1

    # 2. Check Key Environment Variables
    print("\n--- Checking Environment Variables ---")
    # Add any specific tokens or mode variables your project expects
    expected_vars = ["DATABASE_URL", "ENVIRONMENT"]
    for var in expected_vars:
        value = os.getenv(var)
        if value:
            # Mask sensitive tokens if displayed
            display_val = value[:8] + "..." if "URL" in var or "KEY" in var else value
            print(f"  [✓] {var} is configured ({display_val})")
        else:
            print(f"  [!] {var} is not set (Optional / Defaulting)")

    # 3. Verify Python Packages
    print("\n--- Verifying Project Dependencies ---")
    if os.path.exists("requirements.txt"):
        try:
            # Run a dry-run install pass or check to see if dependencies are missing
            result = subprocess.run(
                [sys.executable, "-m", "pip", "check"], 
                capture_output=True, 
                text=True
            )
            if result.returncode == 0:
                print("  [✓] All installed Python packages match dependency requirements.")
            else:
                print("  [✗] Dependency conflict detected:")
                print(result.stderr)
                errors += 1
        except Exception as e:
            print(f"  [✗] Failed to run pip check: {e}")
            errors += 1
    else:
        print("  [-] No requirements.txt found in project root. Skipping.")

    # 4. Final Verdict
    print("\n==================================================")
    if errors == 0:
        print("  STATUS: SUCCESS - Sandbox environment is fully ready.")
        print("==================================================")
        sys.exit(0)
    else:
        print(f"  STATUS: FAILED - Found {errors} configuration issue(s).")
        print("==================================================")
        sys.exit(1)

if __name__ == "__main__":
    main()