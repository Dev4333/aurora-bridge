"""Auth Manager — OAuth flow for Bridge Agent authentication.

Opens user's browser to Aurora X login page, receives callback with bridge token
via a local HTTP server, stores token encrypted locally.
"""

import asyncio
import logging
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from threading import Thread

from config_store import save_token

logger = logging.getLogger("aurora-bridge")

CALLBACK_PORT = 19840
CALLBACK_PATH = "/callback"


class _CallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler that receives the OAuth callback with the bridge token."""

    token: str | None = None

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_response(404)
            self.end_headers()
            return

        params = parse_qs(parsed.query)
        token = params.get("token", [None])[0]

        if token:
            _CallbackHandler.token = token
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"""
            <html><body style="font-family: system-ui; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; background: #0a0a0a; color: #fff;">
                <div style="text-align: center;">
                    <h1 style="color: #22c55e;">&#10003; Connected!</h1>
                    <p>Aurora Bridge Agent is now authenticated.</p>
                    <p style="color: #888;">You can close this tab.</p>
                </div>
            </body></html>
            """)
        else:
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"""
            <html><body style="font-family: system-ui; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; background: #0a0a0a; color: #fff;">
                <div style="text-align: center;">
                    <h1 style="color: #ef4444;">&#10007; Error</h1>
                    <p>No token received. Please try again from Aurora X settings.</p>
                </div>
            </body></html>
            """)

    def log_message(self, format, *args):
        # Suppress default HTTP server logs
        pass


class AuthManager:
    """Manages Bridge Agent authentication via OAuth."""

    def __init__(self, api_url: str):
        self.api_url = api_url.rstrip("/")

    async def authenticate(self) -> str | None:
        """Run the full OAuth flow. Returns bridge token or None on failure."""
        callback_url = f"http://localhost:{CALLBACK_PORT}{CALLBACK_PATH}"
        auth_url = f"{self.api_url.replace('/api', '').replace(':3001', ':3000')}/settings?bridge_auth=1&callback={callback_url}"

        logger.info(f"Opening browser for authentication...")
        logger.info(f"If browser doesn't open, visit: {auth_url}")

        # Reset token
        _CallbackHandler.token = None

        # Start local HTTP server in a thread
        server = HTTPServer(("127.0.0.1", CALLBACK_PORT), _CallbackHandler)
        server.timeout = 120  # 2 minute timeout

        def run_server():
            while _CallbackHandler.token is None:
                server.handle_request()
                if _CallbackHandler.token:
                    break

        thread = Thread(target=run_server, daemon=True)
        thread.start()

        # Open browser
        webbrowser.open(auth_url)

        # Wait for callback (max 2 minutes)
        for _ in range(240):  # 240 * 0.5s = 120s
            await asyncio.sleep(0.5)
            if _CallbackHandler.token:
                break

        server.server_close()

        token = _CallbackHandler.token
        if token:
            save_token(token)
            logger.info("Authentication successful!")
            return token
        else:
            logger.error("Authentication timed out or failed.")
            return None
