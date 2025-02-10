# LedController
The docker-based LedController for LS HQ

## Web API

| Method | Path | Description |
| --- | --- | --- |
| GET | /health | Check if the WLEDs are reachable | 
| GET | /videolist | Get a list of all available videos |

## Vidio player

Install the dependencies
```bash
pip install keyboard
```

Run the video player
```bash
python3 play.py
```

## Keybord

Run the following command to start the keyboard light show:

```bash
python3 piano.py
```

Use the following keys to control the light show:

- `ESC` - Quit the light show
- `QWERTYUIOP` - Activate the top windows.
- `ASDFGHJKL;` - Activate the bottom windows.
- `Q` - Activate the top left window (Lawrence).
- `P` - Activate the top right window (Lucas).
- `A` - Activate the bottom left window (Marcel).
- `;` - Activate the bottom right window (Technische Diest).
