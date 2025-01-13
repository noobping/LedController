import socket
import time
import logging
import concurrent.futures
from typing import List, Tuple
import cv2  # OpenCV for video processing
import numpy as np  # For numerical operations
import argparse
import asyncio
import keyboard  # Ensure you have installed 'keyboard' package
import threading

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


def parse_arguments():
    parser = argparse.ArgumentParser(description="WLED Controller with Video Playback")
    parser.add_argument(
        "--video",
        type=str,
        default="video.mp4",
        help="Path to the video file."
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Enable video looping."
    )
    parser.add_argument(
        "--playlist",
        type=str,
        help="Path to the playlist file."
    )
    parser.add_argument(
        "--max-fps",
        type=float,
        default=None,
        help="Maximum frames per second to process."
    )
    return parser.parse_args()


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


def send_packet(ip: str, port: int, packet: bytes, retries: int = 3, delay: float = 0.5) -> None:
    """
    Send a UDP packet to a specified WLED controller with retry logic.

    Args:
        ip: The IP address of the WLED controller.
        port: The port of the WLED controller.
        packet: The DRGB packet to send.
        retries: Number of retry attempts.
        delay: Delay between retries in seconds.
    """
    for attempt in range(retries):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.sendto(packet, (ip, port))
            return  # Success
        except Exception as e:
            logging.warning(f"Failed to send packet to {ip}:{port} on attempt {attempt + 1}/{retries}: {e}")
            time.sleep(delay)
    logging.error(f"All retry attempts failed for {ip}:{port}.")


async def send_packet_async(ip: str, port: int, packet: bytes) -> None:
    """
    Asynchronously send a UDP packet to a specified WLED controller.

    Args:
        ip: The IP address of the WLED controller.
        port: The port of the WLED controller.
        packet: The DRGB packet to send.
    """
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, send_packet, ip, port, packet)


async def send_frames_async(colors: List[Tuple[int, int, int]]) -> None:
    """
    Asynchronously slice the 400-LED color array per controller and send.

    Args:
        colors: A list of RGB tuples (0-255) representing the colors.
    """
    tasks = []
    for idx, ip in enumerate(WLED_IPS):
        # Slice out this controller's 100 LEDs
        start_idx = idx * LEDS_PER_CONTROLLER
        end_idx = start_idx + LEDS_PER_CONTROLLER
        controller_slice = colors[start_idx:end_idx]
        packet = build_packet(controller_slice)
        tasks.append(send_packet_async(ip, PORT, packet))
    await asyncio.gather(*tasks)


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


def play_video(video_path: str, loop: bool = False, max_fps: float = None) -> None:
    """
    Play a video by mapping its frames to the LED windows.

    Args:
        video_path: Path to the video file.
        loop: If True, loop the video playback indefinitely.
        max_fps: Maximum frames per second to process.
    """
    while True:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            logging.error(f"Failed to open video file: {video_path}")
            return

        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps == 0:
            fps = 30  # Default to 30 if FPS detection fails
        if max_fps and fps > max_fps:
            fps = max_fps
            logging.info(f"FPS capped to {fps}")
        frame_duration = 1.0 / fps

        logging.info(f"Playing video: {video_path} at {fps} FPS")

        # Determine the layout of windows (e.g., 4 controllers x 5 windows)
        num_windows = TOTAL_CONTROLLERS * WINDOWS_PER_CONTROLLER  # 20 windows

        # Define the grid size for window mapping (e.g., 4 rows x 5 columns)
        grid_rows = 4
        grid_cols = 5

        while True:
            frame_start_time = time.time()
            ret, frame = cap.read()
            if not ret:
                logging.info("Video playback finished.")
                break  # Exit inner loop to either restart or end

            try:
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
                    logging.error(f"Resized frame has unexpected shape: {resized_frame.shape}")
                    continue  # Skip this frame

                # Extract colors for each window
                reshaped_frame = resized_frame.reshape(-1, 3)  # Shape: (num_windows, 3)
                window_colors = [tuple(pixel.tolist()) for pixel in reshaped_frame]
                logging.debug(f"Window colors: {window_colors}")

                # Validate window_colors length
                if len(window_colors) != num_windows:
                    logging.error(f"Expected {num_windows} window colors, got {len(window_colors)}")
                    continue  # Skip this frame

                # Build the full LED color list using NumPy for efficiency
                full_colors = np.repeat(reshaped_frame, LEDS_PER_WINDOW, axis=0).tolist()

                # Ensure the color list has exactly TOTAL_LEDS entries
                if len(full_colors) < TOTAL_LEDS:
                    full_colors += [(0, 0, 0)] * (TOTAL_LEDS - len(full_colors))
                elif len(full_colors) > TOTAL_LEDS:
                    full_colors = full_colors[:TOTAL_LEDS]

                # Send the colors to the WLED controllers
                send_frames(full_colors)

                # Wait to match the video's frame rate
                elapsed = time.time() - frame_start_time
                time_to_wait = frame_duration - elapsed
                if time_to_wait > 0:
                    time.sleep(time_to_wait)
                else:
                    logging.warning(f"Frame processing is slower ({elapsed:.3f}s) than frame duration ({frame_duration:.3f}s).")

            except Exception as e:
                logging.error(f"An error occurred while processing frame: {e}")
                continue  # Continue with the next frame

        cap.release()

        if not loop:
            break  # Exit outer loop if not looping
        else:
            logging.info("Restarting video playback.")


def play_playlist(playlist_path: str, loop: bool = False, max_fps: float = None) -> None:
    """
    Play a list of videos sequentially.

    Args:
        playlist_path: Path to the playlist file.
        loop: If True, loop the playlist indefinitely.
        max_fps: Maximum frames per second to process.
    """
    try:
        with open(playlist_path, 'r') as f:
            videos = [line.strip() for line in f if line.strip()]
    except Exception as e:
        logging.error(f"Failed to read playlist file: {e}")
        return

    if not videos:
        logging.error("Playlist is empty.")
        return

    while True:
        for video in videos:
            logging.info(f"Starting video playback: {video}")
            play_video(video, loop=False, max_fps=max_fps)

        if not loop:
            break
        else:
            logging.info("Restarting playlist.")


def keyboard_listener(video_path: str, loop: bool = False, max_fps: float = None):
    """
    Listen for keyboard inputs to control video playback.

    Args:
        video_path: Path to the video file.
        loop: If True, loop the video playback.
        max_fps: Maximum frames per second to process.
    """
    logging.info("Press 'v' to play a video, 'q' to quit.")
    while True:
        event = keyboard.read_event()
        if event.event_type == keyboard.KEY_DOWN:
            if event.name == 'v':
                video_path = input("Enter the path to the video file: ")
                logging.info(f"Starting video playback: {video_path}")
                play_video(video_path, loop=loop, max_fps=max_fps)
            elif event.name == 'q':
                logging.info("Quitting...")
                break


def main():
    args = parse_arguments()
    if args.playlist:
        logging.info(f"Starting playlist playback: {args.playlist}")
        play_playlist(args.playlist, loop=args.loop, max_fps=args.max_fps)
    else:
        logging.info(f"Starting video playback: {args.video}")
        play_video(args.video, loop=args.loop, max_fps=args.max_fps)
    logging.info("Playback ended.")


if __name__ == "__main__":
    main()
