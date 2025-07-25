#!/usr/bin/env python3
"""
Test script for debugging the validate_user tool.
This will help identify network issues and test the OTP functionality.
"""

import sys
import os

# Add the app directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

from jarvis.tools.validate_user import debug_api_connection, send_otp, verify_otp, validate_user


def main():
    print("🔧 DealMaker API Validation Tool - Debug Mode")
    print("=" * 50)
    
    # Run comprehensive diagnostics
    print("\n1. Running comprehensive diagnostics...")
    diagnostics = debug_api_connection()
    print(f"Diagnostics result: {diagnostics}")
    
    # Test with a sample email
    print("\n2. Testing OTP send functionality...")
    print("⚠️  This will attempt to send an actual OTP email!")
    
    email = input("Enter email to test (or press Enter to skip): ").strip()
    
    if email:
        print(f"\n📧 Testing send_otp with email: {email}")
        result = send_otp(email)
        print(f"Send OTP result: {result}")
        
        if result.get("success"):
            print("\n✅ OTP sent successfully!")
            code = input("Enter the OTP code you received (or press Enter to skip): ").strip()
            
            if code:
                print(f"\n🔐 Testing verify_otp with code: {code}")
                verify_result = verify_otp(email, code)
                print(f"Verify OTP result: {verify_result}")
                
                if verify_result.get("success"):
                    print("✅ User validation successful!")
                    print(f"Bearer token: {verify_result.get('bearer_token', 'N/A')}")
                else:
                    print("❌ User validation failed!")
            else:
                print("⏭️  Skipping OTP verification test")
        else:
            print("❌ Failed to send OTP!")
    else:
        print("⏭️  Skipping OTP tests")
    
    print("\n🏁 Debug session complete!")
    print("Check the logs above for detailed information about any issues.")


if __name__ == "__main__":
    main() 