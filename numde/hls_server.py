#!/usr/bin/env python3
"""
HLS სერვერი - შიდა მოდული ძირითადი პროექტისთვის
ავტომატურად ელოდებს სტრიმის დაწყებას და გაუშვებს სერვერს
"""

import http.server
import socketserver
import os
import time
import threading
import logging
from pathlib import Path

# HTTP სერვერის ლოგების სრულიად გათიშვა
logging.getLogger("http.server").setLevel(logging.ERROR)
logging.getLogger("socketserver").setLevel(logging.ERROR)
logging.getLogger("http.server.HTTPServer").setLevel(logging.ERROR)

log = logging.getLogger("HLS_SERVER")

class HLSHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory="hls", **kwargs)
    
    def log_message(self, format, *args):
        """HTTP ლოგების გათიშვა"""
        pass  # არ გამოიტანოს HTTP ლოგები
    
    def end_headers(self):
        # CORS headers დამატება
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        # MIME ტიპების დაყენება
        if self.path.endswith('.m3u8'):
            self.send_header('Content-Type', 'application/vnd.apple.mpegurl')
        elif self.path.endswith('.ts'):
            self.send_header('Content-Type', 'video/MP2T')
        super().end_headers()
    
    def do_GET(self):
        # მთავარი გვერდის ჩვენება თუ მოთხოვნა ფესვზეა
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            
            # შევამოწმოთ არსებობს თუ არა სტრიმი
            stream_exists = os.path.exists("hls/wagon_stream.m3u8")
            status_text = "🟢 აქტიური" if stream_exists else "🔴 გათიშული"
            status_color = "#d4edda" if stream_exists else "#f8d7da"
            
            html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>🚂 Wagon Detection Live Stream</title>
    <meta charset="utf-8">
    <style>
        body {{ 
            margin: 0; 
            padding: 20px; 
            font-family: Arial, sans-serif; 
            background: #f0f0f0;
        }}
        .container {{ 
            max-width: 1200px; 
            margin: 0 auto; 
            background: white;
            padding: 20px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        h1 {{ 
            color: #333; 
            text-align: center;
            margin-bottom: 30px;
        }}
        video {{ 
            width: 100%; 
            max-width: 100%; 
            height: auto;
            border: 2px solid #ddd;
            border-radius: 8px;
            background: #000;
        }}
        .info {{
            background: #e8f4fd;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
            border-left: 4px solid #2196F3;
        }}
        .status {{
            background: {status_color};
            padding: 15px;
            border-radius: 5px;
            text-align: center;
            margin-bottom: 20px;
            font-weight: bold;
            font-size: 18px;
        }}
        .controls {{
            text-align: center;
            margin-bottom: 20px;
        }}
        .refresh-btn {{
            background: #007bff;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 5px;
            cursor: pointer;
            font-size: 16px;
        }}
        .refresh-btn:hover {{
            background: #0056b3;
        }}
        .stream-info {{
            background: #fff3cd;
            padding: 10px;
            border-radius: 5px;
            margin-top: 10px;
            font-size: 14px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🚂 Wagon Detection Live Stream</h1>
        
        <div class="status" id="status">
            {status_text} - HLS სტრიმის სტატუსი
        </div>
        
        <div class="controls">
            <button class="refresh-btn" onclick="location.reload()">🔄 გვერდის განახლება</button>
        </div>
        
        <div class="info">
            <strong>📡 HLS სტრიმის ინფორმაცია:</strong><br>
            • ვიდეო: 1280x720 @ 15fps<br>
            • კოდეკი: H.264<br>
            • სეგმენტები: 2 წამი<br>
            • პლეილისტი: /wagon_stream.m3u8
        </div>
        
        <video id="videoPlayer" controls autoplay muted>
            <source src="/wagon_stream.m3u8" type="application/vnd.apple.mpegurl">
            თქვენი ბრაუზერი არ უჭერს მხარდაჭერს HLS სტრიმინგს.
        </video>
        
        <div class="stream-info">
            <strong>💡 მომსახურებელი:</strong><br>
            • სტრიმის სტატუსი ავტომატურად განახლდება ყოველ 5 წამში<br>
            • გამოიყენეთ Chrome, Firefox ან Safari საუკეთესო შედეგისთვის
        </div>
    </div>

    <script>
        const video = document.getElementById('videoPlayer');
        const statusDiv = document.getElementById('status');
        
        // სტატუსის ავტომატური განახლება
        function updateStatus() {{
            fetch('/wagon_stream.m3u8', {{ method: 'HEAD' }})
                .then(response => {{
                    if (response.ok) {{
                        statusDiv.innerHTML = '🟢 აქტიური - HLS სტრიმის სტატუსი';
                        statusDiv.style.background = '#d4edda';
                    }} else {{
                        statusDiv.innerHTML = '🔴 გათიშული - HLS სტრიმის სტატუსი';
                        statusDiv.style.background = '#f8d7da';
                    }}
                }})
                .catch(() => {{
                    statusDiv.innerHTML = '🔴 გათიშული - HLS სტრიმის სტატუსი';
                    statusDiv.style.background = '#f8d7da';
                }});
        }}
        
        // სტატუსის განახლება ყოველ 5 წამში
        setInterval(updateStatus, 5000);
        updateStatus(); // პირველი გაშვება
        
        video.addEventListener('loadstart', function() {{
            console.log('სტრიმის ჩატვირთვა...');
        }});
        
        video.addEventListener('canplay', function() {{
            console.log('სტრიმი მზადაა გასაშვებლად');
        }});
        
        video.addEventListener('error', function() {{
            console.log('სტრიმის შეცდომა');
        }});
        
        // HLS.js ბიბლიოთეკის ჩატვირთვა (თუ საჭიროა)
        if (video.canPlayType('application/vnd.apple.mpegurl') === '') {{
            const script = document.createElement('script');
            script.src = 'https://cdn.jsdelivr.net/npm/hls.js@latest';
            script.onload = function() {{
                if (Hls.isSupported()) {{
                    const hls = new Hls();
                    hls.loadSource('/wagon_stream.m3u8');
                    hls.attachMedia(video);
                }}
            }};
            document.head.appendChild(script);
        }}
    </script>
</body>
</html>
            """
            self.wfile.write(html_content.encode('utf-8'))
            return
        
        # სტანდარტული ფაილების მომსახურება
        super().do_GET()

def wait_for_stream():
    """ელოდებს სტრიმის გაშვებას"""
    log.info("⏳ ველოდები HLS სტრიმის გაშვებას...")
    
    while True:
        if os.path.exists("hls/wagon_stream.m3u8"):
            log.info("✅ HLS სტრიმი აღმოჩნდა!")
            return True
        
        time.sleep(2)

def start_server_in_thread():
    """სერვერის გაშვება ცალკე thread-ში"""
    port = 8080
    
    try:
        with socketserver.TCPServer(("", port), HLSHandler) as httpd:
            log.info(f"🌐 HLS სერვერი გაშვებულია: http://localhost:{port}")
            log.info(f"📺 სტრიმის ნახვა: http://localhost:{port}/")
            log.info(f"🎬 პირდაპირი ბმული: http://localhost:{port}/wagon_stream.m3u8")
            
            # სტრიმის მოლოდინის გაშვება ფონში
            wait_thread = threading.Thread(target=wait_for_stream, daemon=True)
            wait_thread.start()
            
            httpd.serve_forever()
            
    except OSError as e:
        if e.errno == 48:  # Address already in use
            log.error(f"❌ პორტი {port} უკვე გამოიყენება!")
        else:
            log.error(f"❌ სერვერის შეცდომა: {e}")
    except Exception as e:
        log.error(f"❌ სერვერის გაშვების შეცდომა: {e}")

def start_hls_server():
    """HLS სერვერის გაშვება ძირითადი პროგრამიდან"""
    # HLS ფოლდერის შემოწმება
    if not os.path.exists("hls"):
        os.makedirs("hls", exist_ok=True)
        log.info("📁 HLS ფოლდერი შეიქმნა")
    
    # სერვერის გაშვება ცალკე thread-ში
    server_thread = threading.Thread(target=start_server_in_thread, daemon=True)
    server_thread.start()
    
    log.info("🚀 HLS სერვერის thread გაშვებულია")
    return server_thread
