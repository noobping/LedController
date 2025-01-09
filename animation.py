import logging
import socket
import time
import concurrent.futures
from typing import List, Tuple, Callable, Optional

from settings import FPS_TARGET, FRAME_INTERVAL, LEDS_PER_CONTROLLER, PORT, WLED_IPS


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
        packet = bytes([value for color in controller_colors for value in color])
        packets.append((ip, packet))
    return packets


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
    Universal method to run LED animations.

    Args:
        frame_factory (callable): Function that generates a frame. Should return List[Tuple[int, int, int]].
        frame_args (tuple, optional): Positional arguments for frame_factory.
        frame_kwargs (dict, optional): Keyword arguments for frame_factory.
        state (dict, optional): A dictionary to hold any state required by frame_factory.
        frame_interval (float): Duration to display each frame (in seconds).
        fps_target (int): Target frames per second.
        port (int): UDP port to send packets to.
    """
    # Ensure frame_args and frame_kwargs are not None
    frame_args = frame_args or ()
    frame_kwargs = frame_kwargs or {}
    state = state or {"enabled": False}

    logging.info(f"Running animation with a interval of {frame_interval} seconds on {fps_target} FPS")
    logging.info(f"Targeting IPs: {WLED_IPS}, Port: {port}")
    logging.info(
        f"LEDs per controller: {LEDS_PER_CONTROLLER}, Total LEDs: {len(WLED_IPS) * LEDS_PER_CONTROLLER}"
    )

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(WLED_IPS)) as executor:
        while True:
            # Generate the current frame
            try:
                colors_for_all = frame_factory(
                    *frame_args, **frame_kwargs, **state)
            except TypeError as te:
                logging.error(f"Error calling frame_factory: {te}")
                break  # Exit the loop or handle appropriately

            # Build packets for all controllers
            packets = build_packets(colors_for_all)

            # Send packets in parallel
            futures = [
                executor.submit(send_packets, ip, port, packet)
                for ip, packet in packets
            ]
            concurrent.futures.wait(futures)

            # Sleep to maintain the target frame rate
            frame_time = 1.0 / fps_target
            time.sleep(max(frame_interval, frame_time))

            # Toggle the boolean state for the next frame
            if "enabled" in state:
                state["enabled"] = not state["enabled"]
            # Add additional state updates here if necessary
