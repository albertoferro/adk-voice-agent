#!/usr/bin/env python3
"""
Script para probar las interacciones del agente paso a paso.
Esto ayuda a debuguear problemas de consistencia del agente.
"""

import sys
import os
import time

# Add the app directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

from jarvis.tools.validate_user import validate_user
from jarvis.tools.get_investor_info import get_investor_info

def test_agent_flow():
    print("🤖 Testing Agent Flow Simulation")
    print("=" * 50)
    
    # Step 1: Get email from user
    email = input("Enter email for testing: ").strip()
    if not email:
        print("❌ Email required!")
        return
    
    print(f"\n📧 Step 1: Testing OTP send for {email}")
    print("-" * 30)
    
    # Retry logic simulation (like the agent should do)
    max_retries = 3
    otp_success = False
    
    for attempt in range(1, max_retries + 1):
        print(f"🔄 Attempt {attempt}/{max_retries}")
        
        try:
            result = validate_user(email=email)
            
            if result.get("success"):
                print(f"✅ SUCCESS on attempt {attempt}!")
                print(f"📋 Response: {result.get('message')}")
                otp_success = True
                break
            else:
                print(f"❌ FAILED attempt {attempt}: {result.get('message')}")
                if attempt < max_retries:
                    print("⏳ Waiting 5 seconds before retry...")
                    time.sleep(5)
                
        except Exception as e:
            print(f"❌ EXCEPTION on attempt {attempt}: {str(e)}")
            if attempt < max_retries:
                print("⏳ Waiting 5 seconds before retry...")
                time.sleep(5)
    
    if not otp_success:
        print("❌ Failed to send OTP after all retries!")
        return
    
    # Step 2: Get OTP code from user
    print(f"\n🔐 Step 2: Testing OTP verification")
    print("-" * 30)
    
    code = input("Enter the OTP code you received: ").strip()
    if not code:
        print("❌ OTP code required!")
        return
    
    # Retry logic for verification
    verify_success = False
    bearer_token = None
    
    for attempt in range(1, max_retries + 1):
        print(f"🔄 Verify attempt {attempt}/{max_retries}")
        
        try:
            result = validate_user(email=email, code=code)
            
            if result.get("success"):
                print(f"✅ VERIFICATION SUCCESS on attempt {attempt}!")
                bearer_token = result.get("bearer_token")
                print(f"🎯 Bearer token obtained: {bearer_token[:20]}..." if bearer_token else "❌ No bearer token")
                verify_success = True
                break
            else:
                print(f"❌ VERIFICATION FAILED attempt {attempt}: {result.get('message')}")
                if attempt < max_retries:
                    print("⏳ Waiting 3 seconds before retry...")
                    time.sleep(3)
                
        except Exception as e:
            print(f"❌ EXCEPTION on verify attempt {attempt}: {str(e)}")
            if attempt < max_retries:
                print("⏳ Waiting 3 seconds before retry...")
                time.sleep(3)
    
    if not verify_success or not bearer_token:
        print("❌ Failed to verify OTP or get bearer token!")
        return
    
    # Step 3: Test investor info
    print(f"\n📊 Step 3: Testing investor info retrieval")
    print("-" * 30)
    
    for attempt in range(1, max_retries + 1):
        print(f"🔄 Investor info attempt {attempt}/{max_retries}")
        
        try:
            result = get_investor_info(email=email, access_token=bearer_token)
            
            if result.get("success"):
                print(f"✅ INVESTOR INFO SUCCESS on attempt {attempt}!")
                investor_data = result.get("investor_data")
                if investor_data and "items" in investor_data:
                    print(f"📈 Found {len(investor_data['items'])} investment(s)")
                break
            else:
                print(f"❌ INVESTOR INFO FAILED attempt {attempt}: {result.get('message')}")
                if attempt < max_retries:
                    print("⏳ Waiting 3 seconds before retry...")
                    time.sleep(3)
                
        except Exception as e:
            print(f"❌ EXCEPTION on investor info attempt {attempt}: {str(e)}")
            if attempt < max_retries:
                print("⏳ Waiting 3 seconds before retry...")
                time.sleep(3)
    
    print("\n🏁 Agent flow simulation complete!")
    print("\n💡 TIPS:")
    print("- If any step consistently fails, there might be network issues")
    print("- The agent should implement similar retry logic")
    print("- Always check response.success before proceeding")
    print("- Use timeouts and proper error handling")

if __name__ == "__main__":
    test_agent_flow() 