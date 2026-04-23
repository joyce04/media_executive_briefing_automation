"""Simple HTTP health endpoint for monitoring."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import threading
from database.repositories.pipeline_repo import get_last_completed_run
import structlog

logger = structlog.get_logger()


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            try:
                last_run = get_last_completed_run()
                status = {
                    "status": "ok",
                    "last_run_date": dict(last_run)["run_date"] if last_run else None,
                    "last_run_status": dict(last_run)["status"] if last_run else None,
                }
                code = 200
            except Exception as e:
                status = {"status": "error", "error": str(e)}
                code = 500

            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(status).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress default HTTP logging


def start_health_server(port: int = 8080):
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("health_server_started", port=port)
    return server
