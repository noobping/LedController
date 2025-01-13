import socket
import time
import logging
import concurrent.futures
from typing import List, Tuple
import cv2  # OpenCV for video processing
import numpy as np  # For numerical operations

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

# The IPs of your four WLED controllers
WLED_IPS = [
    "192.168.107.123",  # Index 0 -> Top Left
    "192.168.107.122",  # Index 1 -> Top Right
    "192.168.107.120",  # Index 2 -> Bottom Right
    "192.168.107.121",  # Index 3 -> Bottom Left
]

PORT = 19446             # WLED’s real-time UDP port
LEDS_PER_CONTROLLER = 100
WINDOWS_PER_CONTROLLER = 5
LEDS_PER_WINDOW = LEDS_PER_CONTROLLER // WINDOWS_PER_CONTROLLER  # 20
TOTAL_CONTROLLERS = len(WLED_IPS)
TOTAL_LEDS = LEDS_PER_CONTROLLER * TOTAL_CONTROLLERS  # 400
BYTES_PER_LED = 3       # R, G, B


def build_packet(colors: List[Tuple[int, int, int]]) -> bytes:
    """
    Builds the DRGB packet (no header, just RGB bytes) for the entire LED array.

    Args:
        colors: A list of RGB tuples (0-255) representing the colors.

    Returns:
        A byte array representing the DRGB packet.
    """
    colors = colors[::-1]  # Reverse the order of the colors

    packet = bytearray()
    for (r, g, b) in colors:
        packet += bytes([r, g, b])
    return packet


def send_packet(ip: str, port: int, packet: bytes) -> None:
    """
    Send a UDP packet to a specified WLED controller.

    Args:
        ip: The IP address of the WLED controller.
        port: The port of the WLED controller.
        packet: The DRGB packet to send.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.sendto(packet, (ip, port))


def send_frames(colors: List[Tuple[int, int, int]]) -> None:
    """
    Slice the 400-LED color array per controller and send in parallel.

    Args:
        colors: A list of RGB tuples (0-255) representing the colors.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=TOTAL_CONTROLLERS) as executor:
        futures = []
        for idx, ip in enumerate(WLED_IPS):
            # Slice out this controller's 100 LEDs
            start_idx = idx * LEDS_PER_CONTROLLER
            end_idx = start_idx + LEDS_PER_CONTROLLER
            controller_slice = colors[start_idx:end_idx]
            logging.debug(f"Sending to {ip}: {controller_slice}")

            # Build and send this subset
            packet = build_packet(controller_slice)
            futures.append(executor.submit(send_packet, ip, PORT, packet))


def play_video(video_path: str) -> None:
    """
    Play a video by mapping its frames to the LED windows.

    Args:
        video_path: Path to the video file.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logging.error(f"Failed to open video file: {video_path}")
        return

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps == 0:
        fps = 30  # Default to 30 if FPS detection fails
    frame_duration = 1.0 / fps

    logging.info(f"Playing video: {video_path} at {fps} FPS")

    # Determine the layout of windows (e.g., 4 controllers x 5 windows)
    num_windows = TOTAL_CONTROLLERS * WINDOWS_PER_CONTROLLER  # 20 windows

    # Define the grid size for window mapping (e.g., 4 rows x 5 columns)
    grid_rows = 4
    grid_cols = 5

    while True:
        start_time = time.time()
        ret, frame = cap.read()
        if not ret:
            logging.info("Video playback finished.")
            break

        # Check the number of channels in the frame
        if len(frame.shape) == 2:
            # Grayscale image, convert to RGB
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
            logging.debug("Converted grayscale frame to RGB.")
        elif frame.shape[2] == 4:
            # Frame with alpha channel, remove it
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2RGB)
            logging.debug("Converted BGRA frame to RGB.")
        elif frame.shape[2] == 3:
            # BGR to RGB
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            logging.debug("Converted BGR frame to RGB.")
        else:
            logging.error(f"Unexpected number of channels: {frame.shape[2]}")
            continue  # Skip this frame

        # Resize the frame to match the grid size
        resized_frame = cv2.resize(
            frame, (grid_cols, grid_rows), interpolation=cv2.INTER_AREA)
        logging.debug(f"Resized frame shape: {resized_frame.shape}")

        # Ensure resized_frame has shape (grid_rows, grid_cols, 3)
        if resized_frame.shape != (grid_rows, grid_cols, 3):
            logging.error(f"Resized frame has unexpected shape: {
                          resized_frame.shape}")
            continue  # Skip this frame

        # Extract colors for each window
        # Shape: (num_windows, 3)
        reshaped_frame = resized_frame.reshape(-1, 3)
        window_colors = [tuple(pixel.tolist()) for pixel in reshaped_frame]
        logging.info(f"Window colors: {window_colors}")

        # Validate window_colors length
        if len(window_colors) != num_windows:
            logging.error(f"Expected {num_windows} window colors, got {
                          len(window_colors)}")
            continue  # Skip this frame

        # Build the full LED color list
        full_colors = []
        for color in window_colors:
            # Assign the same color to all LEDs in the window
            full_colors.extend([color] * LEDS_PER_WINDOW)

        # Ensure the color list has exactly TOTAL_LEDS entries
        if len(full_colors) < TOTAL_LEDS:
            full_colors += [(0, 0, 0)] * (TOTAL_LEDS - len(full_colors))
        elif len(full_colors) > TOTAL_LEDS:
            full_colors = full_colors[:TOTAL_LEDS]

        # Send the colors to the WLED controllers
        send_frames(full_colors)

        # Wait to match the video's frame rate
        elapsed = time.time() - start_time
        time_to_wait = frame_duration - elapsed
        if time_to_wait > 0:
            time.sleep(time_to_wait)

    cap.release()


def main():
    logging.info("Starting WLED controller with video playback.")
    video_path = "video.mp4"
    logging.info(f"Starting video playback: {video_path}")
    play_video(video_path)
    logging.info("Video playback ended.")


if __name__ == "__main__":
    main()
