#!/usr/bin/env python3
"""
Test script for the get_investor_info tool.
This will help test the investor information retrieval functionality.
"""

import sys
import os

# Add the app directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

from jarvis.tools.get_investor_info import get_investor_info, get_investor_investments, format_investor_data
from jarvis.tools.validate_user import validate_user


def main():
    print("🔧 DealMaker Investor Information Tool - Test Mode")
    print("=" * 55)
    
    print("\n🔐 Step 1: User Authentication Required")
    print("To get investor information, you need to authenticate first.")
    
    email = input("Enter email for authentication: ").strip()
    
    if not email:
        print("❌ Email is required. Exiting...")
        return
    
    # Step 1: Send OTP
    print(f"\n📧 Sending OTP to {email}...")
    otp_result = validate_user(email=email)
    
    if not otp_result.get("success"):
        print(f"❌ Failed to send OTP: {otp_result.get('message')}")
        return
    
    print("✅ OTP sent successfully!")
    
    # Step 2: Verify OTP
    code = input("Enter the OTP code you received: ").strip()
    
    if not code:
        print("❌ OTP code is required. Exiting...")
        return
    
    print(f"\n🔐 Verifying OTP code: {code}")
    auth_result = validate_user(email=email, code=code)
    
    if not auth_result.get("success"):
        print(f"❌ Authentication failed: {auth_result.get('message')}")
        return
    
    print("✅ Authentication successful!")
    
    # Extract bearer token
    bearer_token = auth_result.get("bearer_token")
    
    if not bearer_token:
        print("❌ No bearer token found in authentication response")
        print(f"Auth result: {auth_result}")
        return
    
    print(f"🎯 Bearer token obtained: {bearer_token[:20]}...")
    
    # Step 3: Get investor information
    print(f"\n📊 Getting investor information for {email}...")
    investor_result = get_investor_info(email=email, access_token=bearer_token)
    
    print(f"\nInvestor info result: {investor_result}")
    
    if investor_result.get("success"):
        print("✅ Investor information retrieved successfully!")
        
        # Display investor data if available
        investor_data = investor_result.get("investor_data")
        if investor_data:
            print("\n" + "="*50)
            formatted_summary = format_investor_data(investor_data)
            print(formatted_summary)
            print("="*50)
        else:
            print("⚠️  No investor data found in response")
    else:
        print("❌ Failed to get investor information!")
        print(f"Error: {investor_result.get('message')}")
    
    print("\n🏁 Test complete!")


if __name__ == "__main__":
    main() 