import logging
import time
from typing import Callable, List, Optional, Tuple

import concurrent

WLED_IPS = [
    "192.168.107.122",  # Index 0 -> Top right (Kantoor Lucas)
    "192.168.107.123",  # Index 1 -> Top left (DutchGrit)
    "192.168.107.120",  # Index 2 -> Bottom right (3D Printer)
    "192.168.107.121",  # Index 3 -> Bottom left (Finance)
]
WINDOWS_PER_CONTROLLER = 5
LEDS_PER_CONTROLLER = 100
# 20 LEDs per window
LEDS_PER_WINDOW = LEDS_PER_CONTROLLER // WINDOWS_PER_CONTROLLER  # 20 LEDs per window
WLED_CONTROLLERS = len(WLED_IPS)  # 4 controllers
TOTAL_LEDS = LEDS_PER_CONTROLLER * WLED_CONTROLLERS  # 400 LEDs
BYTES_PER_LED = 3  # R, G, B
FRAME_INTERVAL = 5  # 5 seconds per frame
FPS_TARGET = 15  # Frames per second
PORT = 19446  # WLED’s real-time port


def send_packets(ip: str, port: int, packet: bytes) -> None:
    """
    Send a UDP packet to a specified WLED controller.

    Args:
        ip (str): IP address of the WLED controller.
        port (int): Port number to send the packet to.
        packet (bytes): The packet to send.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.sendto(packet, (ip, port))
            # logging.debug(f"Sent packet of {len(packet)} bytes to {ip}:{port}")
        except Exception as e:
            logging.error(f"Failed to send packet to {ip}:{port} - {e}")


def build_packets(colors_for_all: List[Tuple[int, int, int]]) -> List[Tuple[str, bytes]]:
    """
    Builds the packets for all controllers.

    Args:
        colors_for_all (List[Tuple[int, int, int]]): A list of (R, G, B) tuples for all LEDs.

    Returns:
        List[Tuple[str, bytes]]: A list of (ip, packet) tuples for all controllers.
    """
    packets = []
    for idx, ip in enumerate(WLED_IPS):
        start_idx = idx * LEDS_PER_CONTROLLER
        end_idx = start_idx + LEDS_PER_CONTROLLER
        controller_colors = colors_for_all[start_idx:end_idx]
        # Flatten the list of tuples into bytes
        packet = bytes(
            [value for color in controller_colors for value in color])
        packets.append((ip, packet))
    return packets


def make_christmas_frame(enabled: bool = True, **state) -> List[Tuple[int, int, int]]:
    """
    Create a fixed red-green pattern with blocks of LEDs each, starting with red or green.

    Args:
        enabled (bool): If True, start with red blocks; otherwise, start with green.
        **state: Additional state variables.

    Returns:
        List[Tuple[int, int, int]]: A list of (R, G, B) tuples with red and green colors.
    """
    logging.debug(f"Creating Christmas frame that starts with {
                  'red' if enabled else 'green'}")

    colors = []
    for i in range(TOTAL_LEDS):
        block = i // LEDS_PER_WINDOW  # Determine the block index
        if enabled:
            if block % 2 == 0:
                colors.append((255, 0, 0))  # Red
            else:
                colors.append((0, 255, 0))  # Green
        else:
            if block % 2 == 0:
                colors.append((0, 255, 0))  # Green
            else:
                colors.append((255, 0, 0))  # Red
    return colors


def run_animation_interval(
    frame_factory: Callable[..., List[Tuple[int, int, int]]],
    frame_args: Optional[tuple] = None,
    frame_kwargs: Optional[dict] = None,
    state: Optional[dict] = None,
    frame_interval: float = FRAME_INTERVAL,
    fps_target: int = FPS_TARGET,
    port: int = PORT
) -> None:
    """
    Universal method to run LED animations, generating a new frame
    only every 'frame_interval' seconds, but still sending data at
    'fps_target' times per second.

    Args:
        frame_factory (Callable[..., List[Tuple[int, int, int]]): A function that generates the frame.
        frame_args (Optional[tuple], optional): Positional arguments to pass to the frame_factory. Defaults to None.
        frame_kwargs (Optional[dict], optional): Keyword arguments to pass to the frame_factory. Defaults to None.
        state (Optional[dict], optional): A dictionary to store state. Defaults to None.
        frame_interval (float, optional): The time between frames in seconds. Defaults to FRAME_INTERVAL.
        fps_target (int, optional): The target frames per second. Defaults to FPS_TARGET.
        port (int, optional): The port number to send the packets to. Defaults to PORT.
    """
    frame_args = frame_args or ()
    frame_kwargs = frame_kwargs or {}
    state = state or {}

    logging.info(f"Running animation: new frame every {
                 frame_interval:.2f}s, send at {fps_target} FPS")

    # This will store the "latest" frame so we can re-send it.
    previous_frame = []

    # When it's time to get a new frame
    next_frame_time = time.time()

    with concurrent.futures.ThreadPoolExecutor(max_workers=WLED_CONTROLLERS) as executor:
        while True:
            now = time.time()

            # Time to get a NEW frame?
            if now >= next_frame_time:
                try:
                    # Generate a new frame
                    colors_for_all = frame_factory(
                        *frame_args, **frame_kwargs, **state)
                    previous_frame = colors_for_all  # Cache it
                except TypeError as te:
                    logging.error(f"Error calling frame_factory: {te}")
                    break

                # Set the next time to generate another new frame
                next_frame_time = now + frame_interval

                # Example: toggle some state only when generating new frame
                if "enabled" in state:
                    state["enabled"] = not state["enabled"]
            else:
                # Not yet time for a NEW frame, re-send the old one
                colors_for_all = previous_frame

            # Build packets for all controllers
            packets = build_packets(colors_for_all)

            # Send packets in parallel
            futures = [
                executor.submit(send_packets, ip, port, packet)
                for ip, packet in packets
            ]
            concurrent.futures.wait(futures)

            # Sleep to maintain the target FPS
            time.sleep(1.0 / fps_target)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG,
                        format="%(asctime)s %(levelname)s %(message)s")

    run_animation_interval(
        frame_factory=make_christmas_frame,
        frame_args=(),             # No positional arguments needed
        frame_kwargs={},           # No keyword arguments needed
        state={"enabled": False},   # Initial state
        frame_interval=5,
        fps_target=5
    )
