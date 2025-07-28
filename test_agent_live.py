#!/usr/bin/env python3
"""
Script para probar el agente en vivo y debuguear las llamadas a herramientas.
"""

import sys
import os
import asyncio

# Add the app directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

from jarvis.agent import root_agent
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.adk.runners import Runner

async def test_agent_live():
    print("🤖 Testing Agent Live Interaction")
    print("=" * 50)
    
    # Create session service
    session_service = InMemorySessionService()
    
    # Create a session
    session = await session_service.create_session(
        app_name="Debug Test",
        user_id="test_user",
        session_id="test_session",
    )
    
    # Create runner
    runner = Runner(
        app_name="Debug Test",
        agent=root_agent,
        session_service=session_service,
    )
    
    print("✅ Agent and session created successfully")
    print(f"Agent tools: {[tool.__name__ for tool in root_agent.tools]}")
    
    # Test messages
    test_messages = [
        "Hola, quiero autenticarme",
        "Mi email es alberto@dealmaker.tech",
    ]
    
    for message in test_messages:
        print(f"\n👤 USER: {message}")
        print("🤖 AGENT: Processing...")
        
        try:
            # Send message to agent
            response = await runner.send_message(
                session_id="test_session",
                message=message
            )
            
            print(f"📝 RESPONSE TYPE: {type(response)}")
            print(f"📝 RESPONSE: {response}")
            
        except Exception as e:
            print(f"❌ ERROR: {str(e)}")
            print(f"❌ ERROR TYPE: {type(e).__name__}")
    
    print("\n🏁 Test complete!")

if __name__ == "__main__":
    asyncio.run(test_agent_live()) 