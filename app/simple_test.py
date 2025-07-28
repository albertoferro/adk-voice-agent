#!/usr/bin/env python3
"""
Servidor HTTP simple para probar webhooks
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class WebhookHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        logger.info(f"GET {self.path}")
        
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            response = {"status": "healthy", "service": "DealMaker Webhook Test"}
            self.wfile.write(json.dumps(response).encode())
        
        elif self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            response = {
                "message": "DealMaker Voice Webhook Server",
                "endpoints": {
                    "webhook": "/twiml (POST)",
                    "health": "/health (GET)"
                },
                "status": "ready"
            }
            self.wfile.write(json.dumps(response).encode())
        
        else:
            self.send_response(404)
            self.end_headers()
    
    def do_POST(self):
        logger.info(f"POST {self.path}")
        
        if self.path in ['/twiml', '/twiml/']:
            # Read the request body
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            logger.info(f"📋 Received data: {post_data.decode()}")
            
            # Send TwiML response
            twiml_response = '''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="alice">Hello! This is a test of the DealMaker voice webhook. Your webhook is working correctly!</Say>
    <Pause length="1"/>
    <Say voice="alice">You can now configure your Twilio phone number to use this webhook URL.</Say>
</Response>'''
            
            self.send_response(200)
            self.send_header('Content-type', 'application/xml')
            self.end_headers()
            self.wfile.write(twiml_response.encode())
            logger.info("📤 Sent TwiML response")
        
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        # Custom logging to avoid default format
        logger.info(f"HTTP: {format % args}")

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 8080))
    
    server = HTTPServer(('0.0.0.0', port), WebhookHandler)
    logger.info(f"🚀 Starting simple webhook server on port {port}")
    logger.info(f"📍 Webhook URL will be: http://your-domain.com/twiml")
    logger.info(f"💚 Health check: http://localhost:{port}/health")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("🛑 Server stopped")
        server.shutdown() 