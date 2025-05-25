import asyncio
import websockets
import json
import random
import time
import logging
from colorama import Fore, Style, init

init(autoreset=True)

class RateLimiter:
    """Simple rate limiter to limit actions per time window"""
    def __init__(self, max_calls, period):
        self.max_calls = max_calls
        self.period = period
        self.calls = []
        
    async def wait(self):
        now = time.time()
        # Buang call yang sudah lewat periode
        self.calls = [call for call in self.calls if now - call < self.period]
        if len(self.calls) >= self.max_calls:
            wait_time = self.period - (now - self.calls[0])
            await asyncio.sleep(wait_time)
        self.calls.append(time.time())

class ProxyManager:
    """Manage proxy rotation and blacklist for safety"""
    def __init__(self, proxies):
        self.proxies = proxies or []
        self.blacklist = set()
        self.index = 0

    def get_next_proxy(self):
        if not self.proxies:
            return None
        start_index = self.index
        while True:
            proxy = self.proxies[self.index % len(self.proxies)]
            self.index += 1
            if proxy not in self.blacklist:
                return proxy
            if self.index % len(self.proxies) == start_index:
                # Semua proxy diblacklist
                return None

    def blacklist_proxy(self, proxy):
        self.blacklist.add(proxy)

class GrassBot:
    def __init__(self, accounts, nodes, proxies=None, use_proxy=True):
        self.accounts = accounts
        self.nodes = nodes
        self.proxy_manager = ProxyManager(proxies)
        self.use_proxy = use_proxy and bool(proxies)
        self.connections = {}
        self.loop = asyncio.get_event_loop()
        self.extensions = []
        self.rate_limiter = RateLimiter(max_calls=10, period=60)  # contoh max 10 aksi / menit
        self.log("INFO", f"Bot initialized with {len(accounts)} accounts, {len(nodes)} nodes, proxy enabled: {self.use_proxy}")

    def log(self, tag, msg, color="green"):
        colors = {
            "green": Fore.GREEN,
            "red": Fore.RED,
            "yellow": Fore.YELLOW,
            "cyan": Fore.CYAN,
            "magenta": Fore.MAGENTA,
            "white": Fore.WHITE,
        }
        c = colors.get(color, Fore.WHITE)
        print(f"{c}[{tag}]{Style.RESET_ALL} {msg}")

    async def connect_account(self, account, node_url):
        username = account["username"]
        token = account["token"]
        reconnect_attempts = 0

        # Tambah random jitter delay saat mulai koneksi biar gak serentak
        jitter_delay = random.uniform(1, 5)
        self.log("WAIT", f"{username} waiting {jitter_delay:.2f}s before connecting", "yellow")
        await asyncio.sleep(jitter_delay)

        while True:
            proxy = None
            if self.use_proxy:
                proxy = self.proxy_manager.get_next_proxy()

            try:
                self.log("CONNECT", f"{username} connecting to {node_url} with proxy {proxy}", "yellow")

                # Jika pakai proxy, perlu integrasi proxy tunneling (tidak langsung didukung websockets)
                # Untuk contoh, kita connect langsung tanpa proxy support
                ws = await websockets.connect(node_url)
                self.connections[username] = ws

                # Kirim auth token
                auth_msg = json.dumps({"action": "auth", "token": token})
                await ws.send(auth_msg)
                self.log("AUTH", f"{username} sent auth", "green")

                # Jalankan extension hook on_connect
                for ext in self.extensions:
                    await ext.on_connect(ws, account)

                reconnect_attempts = 0
                await self.listen(ws, account)

            except websockets.exceptions.InvalidStatusCode as e:
                self.log("ERROR", f"{username} invalid status code {e.status_code}, possibly banned or blocked. Rotating proxy.", "red")
                if proxy:
                    self.proxy_manager.blacklist_proxy(proxy)
                await asyncio.sleep(10 + random.uniform(0, 5))

            except Exception as e:
                self.log("ERROR", f"{username} connection error: {e}", "red")
                if proxy:
                    self.proxy_manager.blacklist_proxy(proxy)

                reconnect_attempts += 1
                backoff = min(60, 2 ** reconnect_attempts + random.uniform(0, 5))
                self.log("RECONNECT", f"{username} reconnecting in {backoff:.1f}s", "yellow")
                await asyncio.sleep(backoff)

    async def listen(self, ws, account):
        username = account["username"]
        try:
            async for message in ws:
                self.log("RECV", f"{username}: {message}", "magenta")
                data = json.loads(message)
                for ext in self.extensions:
                    await ext.on_message(ws, account, data)
        except websockets.ConnectionClosed:
            self.log("DISCONNECT", f"{username} disconnected, reconnecting...", "red")
        except Exception as e:
            self.log("ERROR", f"{username} listen error: {e}", "red")
        finally:
            try:
                await ws.close()
            except:
                pass

    async def send_action(self, ws, account, message):
        """Kirim aksi dengan rate limit dan delay acak supaya aman dari deteksi bot"""
        await self.rate_limiter.wait()
        delay = random.uniform(0.5, 2.0)
        await asyncio.sleep(delay)
        await ws.send(json.dumps(message))
        self.log("SEND", f"{account['username']} sent {message}", "cyan")

    def add_extension(self, ext):
        self.extensions.append(ext)
        self.log("EXTENSION", f"Loaded extension {ext.__class__.__name__}", "cyan")

    def start(self):
        for i, account in enumerate(self.accounts):
            node_url = self.nodes[i % len(self.nodes)]
            self.loop.create_task(self.connect_account(account, node_url))
        self.loop.run_forever()


# === Contoh Extension yang lebih cerdas ===
class SmartExtension:
    async def on_connect(self, ws, account):
        # Kirim subscribe / ping dengan delay acak
        await asyncio.sleep(random.uniform(0.5, 1.5))
        msg = {"action": "subscribe", "channel": "updates"}
        await ws.send(json.dumps(msg))

    async def on_message(self, ws, account, data):
        # Respon ping dengan pong
        if data.get("type") == "ping":
            await ws.send(json.dumps({"type": "pong"}))
        # Contoh: Kirim aksi acak dengan delay (simulasi aktivitas manusia)
        if random.random() < 0.1:
            action = {"action": "do_something", "timestamp": time.time()}
            await asyncio.sleep(random.uniform(1, 3))
            await ws.send(json.dumps(action))

def load_proxy_list(filename="proxy.txt"):
    try:
        with open(filename, "r") as f:
            return [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        return []

if __name__ == "__main__":
    # ==== KONFIGURASI AKUN ====
    accounts = [
        {"username": "user1", "token": "token1"},
        {"username": "user2", "token": "token2"},
        {"username": "user3", "token": "token3"},
        # Tambah akun sebanyak yang kamu mau
    ]

    # ==== KONFIGURASI NODE GRASS ====
    nodes = [
        "wss://grass-node1.example.com/ws",
        "wss://grass-node2.example.com/ws",
        # Tambah node sebanyak yang kamu mau
    ]

    # ==== LOAD PROXY DARI FILE ====
    proxies = load_proxy_list("proxy.txt")

    # Buat bot instance
    bot = GrassBot(accounts, nodes, proxies=proxies, use_proxy=True)

    # Tambahkan extension cerdas
    bot.add_extension(SmartExtension())

    # Mulai bot
    bot.start()
