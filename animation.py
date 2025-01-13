import logging
import socket
import time
import concurrent.futures
from typing import List, Tuple, Callable, Optional

from settings import FPS_TARGET, FRAME_INTERVAL, LEDS_PER_CONTROLLER, PORT, WLED_CONTROLLERS, WLED_IPS


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


def run_animation(
    frame_factory: Callable[..., List[Tuple[int, int, int]]],
    frame_args: Optional[tuple] = None,
    frame_kwargs: Optional[dict] = None,
    fps_target: int = FPS_TARGET,
    port: int = PORT
) -> None:
    """
    Universal method to run LED animations, generating a new frame
    every 1/FPS_TARGET seconds, and sending data at FPS_TARGET times per second.

    Args:
        frame_factory (Callable[..., List[Tuple[int, int, int]]): A function that generates the frame.
        frame_args (Optional[tuple], optional): Positional arguments to pass to the frame_factory. Defaults to None.
        frame_kwargs (Optional[dict], optional): Keyword arguments to pass to the frame_factory. Defaults to None.
        fps_target (int, optional): The target frames per second. Defaults to FPS_TARGET.
        port (int, optional): The port number to send the packets to. Defaults to PORT.
    """
    frame_interval = 1.0 / fps_target
    frames_sent = 0
    start_time = time.time()
    fps_counter = 0.0

    logging.info("Starting WLED parallel sender with DNRGB protocol...")
    logging.info(
        f"Targeting IPs: {WLED_IPS}, Port: {port}, FPS: {fps_target}"
    )

    # Use a ThreadPoolExecutor to send packets “in parallel”
    # Set max_workers to the total number of packets per frame to avoid bottleneck
    # For 4 controllers with 2 packets each: 8 workers
    with concurrent.futures.ThreadPoolExecutor(max_workers=WLED_CONTROLLERS * 2) as executor:
        while True:
            colors_for_all = frame_factory(
                *frame_args, **frame_kwargs, fps_counter=fps_counter)

            # Build packets for all controllers
            try:
                # Build packets for all controllers
                packets = build_packets(colors_for_all)
            except ValueError as ve:
                logging.error(f"Error building packets: {ve}")
                break

            # Send all packets concurrently to all controllers
            [
                executor.submit(send_packets, ip, port, packet)
                for ip, packet in packets
            ]

            frames_sent += 1

            # Calculate and log FPS every second
            now = time.time()
            elapsed = now - start_time
            if elapsed >= 1.0:
                fps = frames_sent / elapsed
                logging.info(f"Measured FPS: {fps:.2f}")
                frames_sent = 0
                start_time = now

            # Maintain target FPS and increment time
            time.sleep(frame_interval)
            fps_counter += frame_interval
