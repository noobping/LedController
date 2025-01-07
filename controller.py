import socket
import time
import math
import concurrent.futures
import logging

# Configure basic logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)

WLED_IPS = [
    "192.168.107.123",
    "192.168.107.122",
    "192.168.107.120",
    "192.168.107.121"
]

# Suppose each controller has 100 LEDs in DRGB
NUM_LEDS = 100
BYTES_PER_LED = 3   # R, G, B
FPS_TARGET = 60
PORT = 19446 # WLED’s real-time DRGB port

def make_rainbow_frame(t):
    """
    Returns a list of (R, G, B) tuples for NUM_LEDS
    Example: a simple sine-wave rainbow.
    """
    colors = []
    for i in range(NUM_LEDS):
        r = int((math.sin(t + i*0.06) + 1) * 127)
        g = int((math.sin(t + i*0.06 + 2*math.pi/3) + 1) * 127)
        b = int((math.sin(t + i*0.06 + 4*math.pi/3) + 1) * 127)
        colors.append((r, g, b))
    return colors

def build_packet(colors):
    """
    Builds the DRGB packet (no header, just RGB bytes).
    """
    packet = bytearray()
    for (r, g, b) in colors:
        packet += bytes([r, g, b])
    return packet

def send_packet(ip, port, packet):
    """Sends a UDP packet to one WLED IP."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(packet, (ip, port))
        # 2. Log that we sent a packet
        logging.debug(f"Sent packet of length {len(packet)} bytes to {ip}:{port}")
    except Exception as e:
        logging.error(f"Failed to send packet to {ip}:{port} - {e}")
    finally:
        sock.close()

def main():
    frame_interval = 1.0 / FPS_TARGET
    
    # Variables for FPS measurement
    frames_sent = 0
    start_time = time.time()

    t = 0.0

    # Log startup info
    logging.info("Starting WLED parallel sender...")
    logging.info(f"Targeting IPs: {WLED_IPS}, Port: {PORT}, FPS: {FPS_TARGET}, LEDs per controller: {NUM_LEDS}")
    
    # We can use a ThreadPoolExecutor to dispatch “in parallel”
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(WLED_IPS)) as executor:
        while True:
            # 1) Create the color frame
            colors = make_rainbow_frame(t)
            packet = build_packet(colors)

            # 2) Send the packet to each WLED IP in a separate thread
            futures = []
            for ip in WLED_IPS:
                futures.append(executor.submit(send_packet, ip, PORT, packet))
            
            # Wait for all sends to complete before next frame
            concurrent.futures.wait(futures)
            
            frames_sent += 1

            # 3) Calculate and print FPS every second
            now = time.time()
            elapsed = now - start_time
            if elapsed >= 1.0:
                fps = frames_sent / elapsed
                logging.info(f"Measured FPS: {fps:.2f}")
                # Reset counters
                frames_sent = 0
                start_time = now

            time.sleep(frame_interval)
            t += frame_interval

if __name__ == "__main__":
    main()
