import socket
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

# Each controller’s position mapped to its IP
controllers = {
    "top_left":     "192.168.107.122",
    "top_right":    "192.168.107.123",
    "bottom_right": "192.168.107.120",
    "bottom_left":  "192.168.107.121"
}

# We know each controller has 5 strips, each 100 LEDs => total 500 LEDs
LEDS_PER_STRIP = 100
NUM_STRIPS = 5
TOTAL_LEDS = LEDS_PER_STRIP * NUM_STRIPS  # 500
PORT = 19446  # WLED Realtime DRGB port

def build_packet(color_array):
    """
    Build a DRGB packet: 3 bytes per LED in order [R, G, B].
    color_array = list of (R,G,B) of length TOTAL_LEDS.
    """
    packet = bytearray()
    for (r, g, b) in color_array:
        packet += bytes([r, g, b])
    return packet

def set_strip_color(sockets, position, strip_index, color):
    """
    Sets exactly one 'strip_index' (0..4) on the given 'position' controller 
    to the specified (R,G,B) color, and turns all others off.

    :param sockets: dict of { position: socket.socket }
    :param position: which controller? e.g. "top_left", "top_right", etc.
    :param strip_index: which strip? (0-based, 0..4)
    :param color: (r,g,b) tuple, each 0..255
    """

    if strip_index < 0 or strip_index >= NUM_STRIPS:
        logging.error(f"Invalid strip_index {strip_index}")
        return

    # Create an array for all 500 LEDs
    color_array = [(0,0,0)] * TOTAL_LEDS

    # Determine the LED indices for the chosen strip
    start_idx = strip_index * LEDS_PER_STRIP
    end_idx = start_idx + LEDS_PER_STRIP  # exclusive

    # Fill that slice with the chosen color
    for i in range(start_idx, end_idx):
        color_array[i] = color

    # Build the DRGB packet
    packet = build_packet(color_array)

    # Send the packet over UDP to the controller
    ip = controllers[position]
    try:
        sock = sockets[position]
        sock.sendto(packet, (ip, PORT))
        logging.info(f"Set {position} strip #{strip_index} to color={color}")
    except Exception as e:
        logging.error(f"Failed to send to {position} ({ip}): {e}")

def main():
    # 1) Create a socket for each controller (one-time)
    sockets = {}
    for pos, ip in controllers.items():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sockets[pos] = s

    # 2) Example usage: set top_left’s strip #2 to pure red
    set_strip_color(sockets, "top_left", 2, (255, 0, 0))

    # 3) Example: set bottom_right’s strip #0 to green
    set_strip_color(sockets, "bottom_right", 0, (0, 255, 0))

    # 4) Example: set bottom_left’s strip #4 to white
    set_strip_color(sockets, "bottom_left", 4, (255, 255, 255))

    # 5) Example: set top_right’s strip #1 to purple
    set_strip_color(sockets, "top_right", 1, (255, 0, 255))

    # Cleanup sockets (if desired, or let program exit)
    for s in sockets.values():
        s.close()

if __name__ == "__main__":
    main()
