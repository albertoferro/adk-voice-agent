#!/usr/bin/env python3
"""
Servidor de prueba simple para verificar webhooks de Twilio
"""

from quart import Quart, request
from quart.helpers import make_response
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Quart(__name__)

@app.route('/twiml', methods=['POST'])
async def handle_incoming_call():
    """TwiML endpoint for incoming calls"""
    logger.info("📞 Incoming call received!")
    
    # Log request details
    form_data = await request.form
    logger.info(f"📋 Form data: {dict(form_data)}")
    
    # Get the base URL for WebSocket connection
    base_url = request.url_root.replace('http', 'ws').rstrip('/')
    websocket_url = f"{base_url}/voice"
    
    # TwiML response to connect call to WebSocket
    twiml_response = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice">Hello! This is a test of the DealMaker voice webhook. Your webhook is working correctly!</Say>
    <Connect>
        <Stream url="{websocket_url}" />
    </Connect>
</Response>'''
    
    logger.info(f"📤 Sending TwiML response")
    response = await make_response(twiml_response)
    response.headers['Content-Type'] = 'application/xml'
    return response

@app.websocket('/voice')
async def voice_websocket():
    """WebSocket endpoint for Twilio media streams"""
    logger.info("🔌 WebSocket connection established")
    try:
        while True:
            message = await websocket.receive()
            logger.info(f"📨 WebSocket message: {message}")
            # Simple echo for testing
            await websocket.send('{"event": "connected", "protocol": "Call", "version": "1.0.0"}')
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        logger.info("🔌 WebSocket connection closed")

@app.route('/health')
async def health_check():
    """Health check endpoint"""
    logger.info("💚 Health check requested")
    return {"status": "healthy", "service": "DealMaker Voice Webhook Test"}

@app.route('/')
async def index():
    """Root endpoint with webhook information"""
    return {
        "message": "DealMaker Voice Webhook Server",
        "endpoints": {
            "webhook": "/twiml (POST)",
            "websocket": "/voice (WebSocket)",
            "health": "/health (GET)"
        },
        "status": "ready"
    }

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 8080))
    logger.info(f"🚀 Starting test webhook server on port {port}")
    app.run(host='0.0.0.0', port=port, debug=True) 